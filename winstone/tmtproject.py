import tmt
import os
import os.path
from os.path import join, basename, relpath
import shutil
import xml.etree.ElementTree as ET
from OrderedDict import OrderedDict

xmlFileTypes = [ 'web.xml', 'urlrewrite.xml' ]
class Project(tmt.EclipseProject):
	def __init__(self, *args, **kwargs):
		tmt.EclipseProject.__init__(self, *args, **kwargs)
		tmt.WinstoneServer = self
		self.main = "net.gnehzr.tnoodle.server.TNoodleServer"
		self.argv = [ '--nobrowser', '--consoleLevel=INFO' ]

        # It is important that when we iterate through the plugins
        # in topological sorted order. This way if B uses A, B can clobber
        # A's settings.
		self.plugins = OrderedDict()

	def configure(self):
		tmt.EclipseProject.configure(self)

		self.nonJavaSrcDeps |= tmt.glob(self.srcResource, '.*$', relativeTo=self.srcResource)
		for f in xmlFileTypes:
			self.nonJavaSrcDeps -= tmt.glob(self.srcResource, "%s$" % f, relativeTo=self.srcResource)

	def addPlugin(self, project, needsDb=False):
		project.main = self.main
		project.argv = self.argv

		self.plugins[project.name] = project
		project.needsDb = needsDb

		notDotfile = lambda dirname: not dirname.startswith(".")
		def wrapCompile(ogCompile):
			def newCompile(self):
				if ogCompile(self):
					assert self.webContent
					for dirpath, dirnames, filenames in os.walk(self.webContent):
						dirnames[:] = filter(notDotfile, dirnames) # Note that we're modifying dirnames in place

						if "WEB-INF" in dirnames:
							dirnames.remove("WEB-INF")
						for filename in filter(notDotfile, filenames):
							path = os.path.normpath(os.path.join(dirpath, filename))
							pathRelToWebContent = relpath(path, self.webContent)
							name = join(tmt.WinstoneServer.binResource, "webapps", "ROOT", pathRelToWebContent)
							linkParent = os.path.dirname(name)
							if not os.path.exists(linkParent):
								os.makedirs(linkParent)
							else:
								assert os.path.isdir(linkParent)
							tmt.createSymlinkIfNotExistsOrStale(relpath(path, linkParent), name)
					tmt.WinstoneServer.mungeXmlFiles(topLevelWebProject=self)
			return newCompile
		project.__class__.compile = wrapCompile(project.__class__.compile)

		def webContentDist(self):
			# We just compiled ourself, which caused a recompile
			# of winstone server, so there's no need to recompile it.
			# In fact, recompiling it would be bad, as it would nuke
			# our carefully constructed tnoodle_resources.
			tmt.WinstoneServer.dist(noRemake=True)
			tmt.WinstoneServer.distJarFile()
			shutil.copy(tmt.WinstoneServer.distJarFile(), self.distJarFile())
		project.__class__.webContentDist = webContentDist

	def compile(self):
		if tmt.EclipseProject.compile(self):
			if tmt.TmtProject.projects[tmt.args.project] == self:
				self.mungeXmlFiles(topLevelWebProject=self)

	def mungeXmlFiles(self, topLevelWebProject):
		for f in xmlFileTypes:
			deps = topLevelWebProject.getRecursiveDependenciesTopoSorted()

			webappsDir = join(self.binResource, "webapps")
			webappDir = join(webappsDir, "ROOT")
			webappWebInfDir = join(webappDir, "WEB-INF")
			if not os.path.isdir(webappWebInfDir):
				os.makedirs(webappWebInfDir)

			srcWebInfDir = join(self.srcResource, "webapps", "ROOT", "WEB-INF")
			xmlRoot = ET.parse(join(srcWebInfDir, f)).getroot()
			for project in deps:
				if project in self.plugins.values():
					assert project.webContent
					pluginXmlFile = join(project.webContent, "WEB-INF", f)
					if not os.path.exists(pluginXmlFile):
						continue
					tree = ET.parse(pluginXmlFile)
					root = tree.getroot()
					for child in reversed(root):
						xmlRoot.insert(0, child)

			xmlFile = join(webappWebInfDir, f)
			xmlFileOut = open(xmlFile, 'w')

			ET.register_namespace("", "http://java.sun.com/xml/ns/javaee")

			xmlFileOut.write(ET.tostring(xmlRoot))
			xmlFileOut.close()

	def needsDb(self):
		if tmt.args.project == None:
			# None may not yet be a key in tmt.TmtProject.projects,
			# we just hack around this by unconditionally returning True here.
			return True
		webProject = tmt.TmtProject.projects[tmt.args.project]
		deps = webProject.getRecursiveDependenciesTopoSorted(exclude=set([self]))

		for project in deps:
			if project in self.plugins.values():
				if project.needsDb:
					return True

		return False

	def getJars(self, includeCompileTimeOnlyDependencies=False):
		jars = tmt.EclipseProject.getJars(self, includeCompileTimeOnlyDependencies=includeCompileTimeOnlyDependencies)
		if self.needsDb():
			jars.append(tmt.TmtProject.projects['h2-1.3.169.jar'])

		return jars

	def tweakJarFile(self, jar):
        # We don't necessarily want all the plugins in self.plugins to load here,
        # we only want the ones that the project we're currently building somehow
        # depends on.
		webProject = tmt.TmtProject.projects[tmt.args.project]

		# Out jar file already contains everything needed to start up winstone.
		# All the contents of tnoodle_resources are there too (including webroot).
		# The problem is that even after compiling, webroot/WEB-INF/lib/ and
		# webroot/WEB-INF/classes/ are still unpopulated, so simply jarring it up
		# isn't good enough. Here we populate classes/ and lib/. To do so, we need
		# all of the things that webProject depends on, EXCEPT for winstone (ourself).
		deps = webProject.getRecursiveDependenciesTopoSorted(exclude=set([self]))

		webInf = join("tnoodle_resources", "webapps", "ROOT", "WEB-INF")
		libDir = join(webInf, "lib")
		classesDir = join(webInf, "classes")
		for project in deps:
			assert project is not self
			if hasattr(project, "jarFile"):
				arcPath = join(libDir, basename(project.jarFile))
				jar.write(project.jarFile, arcPath)
			elif isinstance(project, tmt.EclipseProject):
				for dirpath, dirnames, filenames in os.walk(project.bin, followlinks=True):
					for name in filenames:
						path = join(dirpath, name)
						arcPath = join(classesDir, basename(path))
						jar.write(path, arcPath)


Project(tmt.projectName(), description="Tiny embeddable webserver that implements the java servlet spec.")