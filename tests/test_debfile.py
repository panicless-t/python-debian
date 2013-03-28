#! /usr/bin/python

# Tests for ArFile/DebFile
# Copyright (C) 2007    Stefano Zacchiroli  <zack@debian.org>
# Copyright (C) 2007    Filippo Giunchedi   <filippo@debian.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import

import unittest
import os
import re
import stat
import sys
import tempfile
import uu

import six

sys.path.insert(0, '../lib/')

from debian import arfile
from debian import debfile

class TestGNULongArFileFormat(unittest.TestCase):
    def setUp(self):
        os.system("ar r testlong.ar test_debian_support.py test_deb822.py test_changelog_full_stops >/dev/null 2>&1")
        assert os.path.exists("testlong.ar")
        self.a = arfile.ArFile("testlong.ar", mode='a')

    def tearDown(self):
        if os.path.exists('testlong.ar'):
            os.unlink('testlong.ar')

    def test_long_filenames(self):
        self.assertEqual(len(self.a.getmembers()), 3)

        # test presence of a file with long filename
        self.assertEqual(self.a.getmember('test_debian_support.py').name, 'test_debian_support.py')
        
        m = self.a.getmember('test_debian_support.py')
        f = open('test_debian_support.py', 'rb')
        self.assertEqual(m.read(), f.read())
        f.close()

class TestBSDLongArFileFormat(TestGNULongArFileFormat):
    def setUp(self):
        os.system("bsdtar -c --format ar -f testlong.ar test_debian_support.py test_deb822.py test_changelog_full_stops >/dev/null 2>&1")
        assert os.path.exists("testlong.ar")
        self.a = arfile.ArFile("testlong.ar", mode='a')

    def tearDown(self):
        if os.path.exists('testlong.ar'):
            os.unlink('testlong.ar')


class TestArFileWriting(unittest.TestCase):
    def setUp(self):
        os.system("ar r test.ar test_changelog test_deb822.py >/dev/null 2>&1") 
        assert os.path.exists("test.ar")
        with os.popen("ar t test.ar") as ar:
            self.testmembers = [x.strip() for x in ar.readlines()]
        self.a = arfile.ArFile("test.ar", mode='a')

    def tearDown(self):
        if os.path.exists('test.ar'):
            os.unlink('test.ar')

    def test_adding(self):
        self.a.add('test_debfile.py')
        m = self.a.getmember('test_debfile.py')
        self.assertEqual(m.name, 'test_debfile.py')
        self.assertEqual(self.a.getmembers()[-1], m)

        self.a2 = arfile.ArFile('test.ar', mode='r')
        m2 = self.a2.getmember('test_debfile.py')

    def test_write_mode(self):
        self.a.close()
        a = arfile.ArFile(self.a.name, mode='w')
        self.assertEqual(a.getmembers(), [])
        a.add('test_debfile.py')
        
        a2 = arfile.ArFile(self.a.name, mode='r')
        m2 = a2.getmember('test_debfile.py')

class TestBSDArFileWriting(TestArFileWriting):
    def setUp(self):
        os.system("bsdtar -c --format ar -f test.ar test_debfile.py test_changelog test_deb822.py >/dev/null 2>&1") 
        assert os.path.exists("test.ar")
        with os.popen("ar t test.ar") as ar:
            self.testmembers = [x.strip() for x in ar.readlines()]
        self.a = arfile.ArFile("test.ar", mode='a')

    def tearDown(self):
        if os.path.exists('test.ar'):
            os.unlink('test.ar')

class TestArFile(unittest.TestCase):
    def setUp(self):
        os.system("ar r test.ar test_debfile.py test_changelog test_deb822.py >/dev/null 2>&1")
        assert os.path.exists("test.ar")
        with os.popen("ar t test.ar") as ar:
            self.testmembers = [x.strip() for x in ar.readlines()]
        self.a = arfile.ArFile("test.ar")

    def tearDown(self):
        if os.path.exists('test.ar'):
            os.unlink('test.ar')
        if os.path.exists('bsdtest.ar'):
            os.unlink('bsdtest.ar')
    
    def test_getnames(self):
        """ test for file list equality """
        self.assertEqual(self.a.getnames(), self.testmembers)

    def test_getmember(self):
        """ test for each member equality """
        for member in self.testmembers:
            m = self.a.getmember(member)
            assert m
            self.assertEqual(m.name, member)
            
            mstat = os.stat(member)

            self.assertEqual(m.size, mstat[stat.ST_SIZE])
            self.assertEqual(m.owner, mstat[stat.ST_UID])
            self.assertEqual(m.group, mstat[stat.ST_GID])

    def test_file_seek(self):
        """ test for faked seek """
        m = self.a.getmember(self.testmembers[0])

        for i in [10,100,10000,100000]:
            m.seek(i, 0)
            self.assertEqual(m.tell(), i, "failed tell()")
            
            m.seek(-i, 1)
            self.assertEqual(m.tell(), 0, "failed tell()")

        m.seek(0)
        self.assertRaises(IOError, m.seek, -1, 0)
        self.assertRaises(IOError, m.seek, -1, 1)
        m.seek(0)
        m.close()
    
    def test_file_read(self):
        """ test for faked read """
        for m in self.a.getmembers():
            f = open(m.name, 'rb')
        
            for i in [10, 100, 10000]:
                self.assertEqual(m.read(i), f.read(i))
        
            m.close()
            f.close()

    def test_file_readlines(self):
        """ test for faked readlines """

        for m in self.a.getmembers():
            f = open(m.name, 'rb')
        
            self.assertEqual(m.readlines(), f.readlines())
            
            m.close()
            f.close()

    def test_armember_reopening(self):
        """ test for reopening a closed member """
        for m in self.a.getmembers():
            m.close()
        for m in self.a.getmembers():
            m.read()
        self.a.close()
        for m in self.a.getmembers():
            self.assertRaises(ValueError, m.read)

    def test_extract(self):
        """ test extraction """
        tmpf = tempfile.NamedTemporaryFile()
        self.a.extract('test_debfile.py', tmpf.name)
        f1 = open(tmpf.name, 'rb')
        f2 = open(__file__, 'rb')
        self.assertEqual(f1.read(), f2.read())
        f1.close()
        f2.close()
        tmpf.close()

        tmpd = tempfile.mkdtemp()
        self.a.extract('test_debfile.py', tmpd)
        tmpf = os.path.join(tmpd, 'test_debfile.py')
        f1 = open(tmpf, 'rb')
        f2 = open(__file__, 'rb')
        self.assertEqual(f1.read(), f2.read())
        f1.close()
        f2.close()
        os.unlink(tmpf)

class TestBSDArFile(TestArFile):
    """Run the same tests for BSD style archive file"""
    def setUp(self):
        os.system("bsdtar -c --format ar -f test.ar test_debfile.py test_changelog test_deb822.py >/dev/null 2>&1")
        assert os.path.exists("test.ar")
        with os.popen("ar t test.ar") as ar:
            self.testmembers = [x.strip() for x in ar.readlines()]
        self.a = arfile.ArFile("test.ar")

    def tearDown(self):
        if os.path.exists('test.ar'):
            os.unlink('test.ar')


class TestDebFile(unittest.TestCase):

    def setUp(self):
        def uudecode(infile, outfile):
            uu_deb = open(infile, 'rb')
            bin_deb = open(outfile, 'wb')
            uu.decode(uu_deb, bin_deb)
            uu_deb.close()
            bin_deb.close()

        self.debname = 'test.deb'
        self.broken_debname = 'test-broken.deb'
        self.bz2_debname = 'test-bz2.deb'
        uudecode('test.deb.uu', self.debname)
        uudecode('test-broken.deb.uu', self.broken_debname)
        uudecode('test-bz2.deb.uu', self.bz2_debname)

        self.debname = 'test.deb'
        uu_deb = open('test.deb.uu', 'rb')
        bin_deb = open(self.debname, 'wb')
        uu.decode(uu_deb, bin_deb)
        uu_deb.close()
        bin_deb.close()
        self.d = debfile.DebFile(self.debname)

    def tearDown(self):
        self.d.close()
        os.unlink(self.debname)
        os.unlink(self.broken_debname)
        os.unlink(self.bz2_debname)

    def test_missing_members(self):
        self.assertRaises(debfile.DebError,
                lambda _: debfile.DebFile(self.broken_debname), None)

    def test_tar_bz2(self):
        bz2_deb = debfile.DebFile(self.bz2_debname)
        # random test on the data part (which is bzipped), just to check if we
        # can access its content
        self.assertEqual(os.path.normpath(bz2_deb.data.tgz().getnames()[10]),
                         os.path.normpath('./usr/share/locale/bg/'))
        bz2_deb.close()

    def test_data_names(self):
        """ test for file list equality """ 
        tgz = self.d.data.tgz()
        with os.popen("dpkg-deb --fsys-tarfile %s | tar t" %
                      self.debname) as tar:
            dpkg_names = [os.path.normpath(x.strip()) for x in tar.readlines()]
        debfile_names = [os.path.normpath(name) for name in tgz.getnames()]
        
        # skip the root
        self.assertEqual(debfile_names[1:], dpkg_names[1:])

    def test_control(self):
        """ test for control equality """
        with os.popen("dpkg-deb -f %s" % self.debname) as dpkg_deb:
            filecontrol = "".join(dpkg_deb.readlines())

        self.assertEqual(
            self.d.control.get_content("control").decode("utf-8"), filecontrol)
        self.assertEqual(
            self.d.control.get_content("control", encoding="utf-8"),
            filecontrol)

    def test_md5sums(self):
        """test md5 extraction from .debs"""
        md5 = self.d.md5sums()
        self.assertEqual(md5[b'usr/bin/hello'],
                '9c1a72a78f82216a0305b6c90ab71058')
        self.assertEqual(md5[b'usr/share/locale/zh_TW/LC_MESSAGES/hello.mo'],
                'a7356e05bd420872d03cd3f5369de42f')
        md5 = self.d.md5sums(encoding='UTF-8')
        self.assertEqual(md5[six.u('usr/bin/hello')],
                '9c1a72a78f82216a0305b6c90ab71058')
        self.assertEqual(md5[six.u('usr/share/locale/zh_TW/LC_MESSAGES/hello.mo')],
                'a7356e05bd420872d03cd3f5369de42f')

if __name__ == '__main__':
    unittest.main()

