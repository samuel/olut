
import os
import subprocess
import unittest

from olut.command import Olut

TEST_PATH = os.path.dirname(os.path.abspath(__file__))
TEMP_PATH = os.path.realpath("/tmp/olut-test")

class BasicTests(unittest.TestCase):
    def cleanTempPath(self):
        subprocess.call("rm -rf %s || true" % TEMP_PATH, shell=True)
    
    def setUp(self):
        self.cleanTempPath()
        self.olut = Olut(TEMP_PATH)

    def tearDown(self):
        self.cleanTempPath()
    
    def testBuild(self):
        self.olut.build(os.path.join(TEST_PATH, "testapp"), TEMP_PATH)
        self.failUnless(os.path.exists("%s/testapp-1.0.tgz" % TEMP_PATH))
    
    def testInstall(self):
        self.testBuild()
        self.olut.install("%s/testapp-1.0.tgz" % TEMP_PATH)
        self.failUnless(os.path.exists("%s/testapp/1.0/code.py" % TEMP_PATH))
    
    def testActivate(self):
        self.testInstall()
        self.olut.activate("testapp", "1.0")
        self.failUnlessEqual(os.path.realpath("%s/testapp/current" % TEMP_PATH), "%s/testapp/1.0" % TEMP_PATH)

    def testDeactivate(self):
        self.testActivate()
        self.olut.deactivate("testapp")
        self.failUnless(not os.path.exists("%s/testapp/current" % TEMP_PATH))
