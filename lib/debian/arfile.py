# ArFile: a Python representation of ar (as in "man 1 ar") archives.
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

from __future__ import print_function

import sys
import os

GLOBAL_HEADER = b"!<arch>\n"
GLOBAL_HEADER_LENGTH = len(GLOBAL_HEADER)

FILE_HEADER_LENGTH = 60
FILE_MAGIC = b"`\n"

class ArError(Exception):
    pass

class ArFile(object):
    """ Representation of an ar archive, see man 1 ar.
    
    The interface of this class tries to mimick that of the TarFile module in
    the standard library.
    
    ArFile objects have the following (read-only) properties:
        - members       same as getmembers()
    """

    def __init__(self, filename=None, mode='r', fileobj=None,
                 encoding=None, errors=None):
        """ Build an ar file representation starting from either a filename or
        an existing file object. The only supported mode is 'r'.

        In Python 3, the encoding and errors parameters control how member
        names are decoded into Unicode strings. Like tarfile, the default
        encoding is sys.getfilesystemencoding() and the default error handling
        scheme is 'surrogateescape' (>= 3.2) or 'strict' (< 3.2).
        """

        self.members = [] 
        self.members_dict = {}
        self.name = filename
        self._fileobj = fileobj
        if encoding is None:
            encoding = sys.getfilesystemencoding()
        self.encoding = encoding
        if errors is None:
            if sys.version >= '3.2':
                errors = 'surrogateescape'
            else:
                errors = 'strict'
        self.errors = errors
        self._modemap = {'r': 'rb', 'a': 'r+b', 'w': 'r+b'}
        self.mode = mode
        if self.mode not in 'raw':
            raise ValueError("Invalid open mode; must be 'r', 'a' or 'w'.")
        if self.mode in 'ra':
            self._index_archive()
        elif self.mode == 'w':
            self._truncate_archive()

    def _index_archive(self):
        if self.name:
            fp = open(self.name, self._modemap[self.mode])
        elif self._fileobj:
            fp = self._fileobj
        else:
            raise ArError("Unable to open valid file")
        if fp.read(GLOBAL_HEADER_LENGTH) != GLOBAL_HEADER:
            raise ArError("Unable to find global header")

        while True:
            newmember = ArMember.from_file(fp, self.name,
                                           encoding=self.encoding,
                                           errors=self.errors,
                                           mode=self.mode)
            if not newmember:
                break
            self.members.append(newmember)
            if self.members[0]._endslash != newmember._endslash:
                raise ValueError("BSD/GNU filename field format mixup.")
            self.members_dict[newmember.name] = newmember
            if newmember.size % 2 == 0: # even, no padding
                fp.seek(newmember.size, 1) # skip to next header
            else:
                fp.seek(newmember.size + 1 , 1) # skip to next header
        
        if self.name:
            fp.close()

    def _truncate_archive(self):
        if self.name:
            fp = open(self.name, 'wb')
        elif self._fileobj:
            fp = self._fileobj
        else:
            raise IOError("Invalid parameters passed, need to specify either filename or fileobj")
        fp.write(GLOBAL_HEADER)
        fp.flush()
        if self.name:
            fp.close()

    def getmember(self, name):
        """ Return the (last occurrence of a) member in the archive whose name
        is 'name'. Raise KeyError if no member matches the given name.

        Note that in case of name collisions the only way to retrieve all
        members matching a given name is to use getmembers. """
        return self.members_dict[name]

    def getmembers(self):
        """ Return a list of all members contained in the archive.

        The list has the same order of members in the archive and can contain
        duplicate members (i.e. members with the same name) if they are
        duplicate in the archive itself. """

        return self.members

    def getnames(self):
        """ Return a list of all member names in the archive. """

        return [f.name for f in self.members]

    def extractall(self, path=None):
        """ Extracts all archive members to specified directory or
        current working directory if path is None. """
        for m in self.getmembers():
            self.extract(m, path)

    def extract(self, member, path=None):
        """ Extracts an archive member to specified path or current working
        directory if path is None. If path is directory, extract into it, else
        use specified name as file name."""
        m = self.extractfile(member)
        if path is None:
            path = '.'
        if os.path.isdir(path):
            path = os.path.join(path, m.name)
        fd = open(path, 'wb')
        m.seek(0)
        fd.write(m.read())
        fd.close()

    def extractfile(self, member):
        """ Return a file object corresponding to the requested member. A member
        can be specified either as a string (its name) or as a ArMember
        instance. """

        # TODO(jsw): What is the point of this method?  It differs from
        # getmember in the following ways:
        #  - It returns the *first* member with the given name instead of the
        #    last.
        #  - If member is an ArMember, it uses that ArMember's name as the key.
        # The former just seems confusing (and this implementation less
        # efficient than getmember's - probably historical), and I'm having a
        # hard time seeing the use-case for the latter.
        for m in self.members:
            if isinstance(member, ArMember) and m.name == member.name:
                return m
            elif member == m.name:
                return m
        return None

    def getarinfo(self):
        pass # FIXME

    def add(self, name):
        if self.mode == 'r':
            raise IOError("File not open for writing")
        if self.name:
            fp = open(self.name, self._modemap[self.mode])
        else:
            fp = self._fileobj
        if self.getmembers() != []:
            endslash = self.getmembers()[0]._endslash
        else:
            endslash = 0
        member = ArMember.from_filename(fp, name, endslash=endslash)
        if self.name:
            fp.close()
        self.members.append(member)
        self.members_dict[member.name] = member

    # container emulation

    def __iter__(self):
        """ Iterate over the members of the present ar archive. """

        return iter(self.__members)

    def __getitem__(self, name):
        """ Same as .getmember(name). """

        return self.getmember(name)

class ArMember(object):
    """ Member of an ar archive.

    Implements most of a file object interface: read, readline, next,
    readlines, seek, tell, close.
    
    ArMember objects have the following (read-only) properties:
        - name      member name in an ar archive
        - mtime     modification time
        - owner     owner user
        - group     owner group
        - fmode     file permissions
        - size      size in bytes
        - fname     file name"""

    def __init__(self):
        self.name = None      # member name (i.e. filename) in the archive
        self._endslash = 0     # member name had trailing slash
        self.mtime = None     # last modification time
        self.owner = None     # owner user
        self.group = None     # owner group
        self.fmode = None     # permissions
        self.size = None      # member size in bytes
        self.fname = None     # file name associated with this member
        self._fp = None        # file pointer 
        self._offset = None    # start-of-data offset
        self._end = None       # end-of-data offset
        self.mode = None      # file open mode

    def from_filename(fp, filename, encoding=None, errors=None, mode='r+b', endslash=0):
        """ Create a ArMember from filename, to be able to include it in archive"""
        f = ArMember()
        st = os.stat(filename)

        fd = open(filename, 'rb')
        f.name = fd.name
        f._endslash = endslash
        f.mtime = int(st.st_mtime)
        f.owner = int(st.st_uid)
        f.group = int(st.st_gid)
        f.fmode = '%o' % st.st_mode
        f.size = st.st_size
        f.fname = fp.name
        
        
        fp.seek(0, os.SEEK_END)
        fp.write(f.getheader())
        f._offset = fp.tell()
        fp.write(fd.read())
        f._end = fp.tell()
        fp.write(f.getpadding())
        fd.close()
        return f
    from_filename = staticmethod(from_filename)

    def from_file(fp, fname, encoding=None, errors=None, mode='rb'):
        """fp is an open File object positioned on a valid file header inside
        an ar archive. Return a new ArMember on success, None otherwise. """
        # FIXME: Mode should probably not be in last position.
        buf = fp.read(FILE_HEADER_LENGTH)

        if not buf:
            return None

        # sanity checks
        if len(buf) < FILE_HEADER_LENGTH:
            raise IOError("Incorrect header length")

        if buf[58:60] != FILE_MAGIC:
            raise IOError("Incorrect file magic")

        if sys.version >= '3':
            if encoding is None:
                encoding = sys.getfilesystemencoding()
            if errors is None:
                if sys.version >= '3.2':
                    errors = 'surrogateescape'
                else:
                    errors = 'strict'

        # http://en.wikipedia.org/wiki/Ar_(Unix)    
        #from   to     Name                      Format
        #0      15     File name                 ASCII
        #16     27     File modification date    Decimal
        #28     33     Owner ID                  Decimal
        #34     39     Group ID                  Decimal
        #40     47     File mode                 Octal
        #48     57     File size in bytes        Decimal
        #58     59     File magic                \140\012

        # XXX struct.unpack can be used as well here
        f = ArMember()
        f.name = buf[0:16].rstrip().split(b"/")[0]
        f._endslash = int(buf[0:16].rstrip().endswith(b"/"))
        if sys.version >= '3':
            f.__name = f.__name.decode(encoding, errors)
        f.mtime = int(buf[16:28])
        f.owner = int(buf[28:34])
        f.group = int(buf[34:40])
        f.fmode  = buf[40:48]  # XXX octal value
        f.size  = int(buf[48:58])

        f.fname = fname
        f._offset = fp.tell() # start-of-data
        f._end = f._offset + f.size
        f.mode = mode

        return f

    from_file = staticmethod(from_file)
    
    # file interface

    # XXX this is not a sequence like file objects
    def _ensure_open(self):
        if self._fp is None:
            self._fp = open(self.fname, self.mode)
            self._fp.seek(self._offset)

    def getheader(self):
        name = self.name
        if self._endslash:
            name += '/'
        if len(name) > 16:
            raise ValueError('Long file names are not supported')
        return '{1: <16}{0.mtime: <9}  {0.owner: <5} {0.group: <5} {0.fmode: <7} {0.size: <10}`\n'.format(self, name)

    def getpadding(self):
        if self.size % 2 == 1:
            return '\n'
        return ''

    def read(self, size=0):
        self._ensure_open()

        cur = self._fp.tell()

        if size > 0 and size <= self._end - cur: # there's room
            return self._fp.read(size)

        if cur >= self._end or cur < self._offset:
            return b''

        return self._fp.read(self._end - cur)

    def readline(self, size=None):
        self._ensure_open()

        if size is not None: 
            buf = self._fp.readline(size)
            if self._fp.tell() > self._end:
                return b''

            return buf

        buf = self._fp.readline()
        if self._fp.tell() > self._end:
            return b''
        else:
            return buf

    def readlines(self, sizehint=0):
        self._ensure_open()
        
        buf = None
        lines = []
        while True: 
            buf = self.readline()
            if not buf: 
                break
            lines.append(buf)

        return lines

    def seek(self, offset, whence=0):
        self._ensure_open()

        if self._fp.tell() < self._offset:
            self._fp.seek(self._offset)

        if whence < 2 and offset + self._fp.tell() < self._offset:
            raise IOError("Can't seek at %d" % offset)
        
        if whence == 1:
            self._fp.seek(offset, 1)
        elif whence == 0:
            self._fp.seek(self._offset + offset, 0)
        elif whence == 2:
            self._fp.seek(self._end + offset, 0)

    def tell(self):
        self._ensure_open()

        cur = self._fp.tell()
        
        if cur < self._offset:
            return 0
        else:
            return cur - self._offset

    def seekable(self):
        return True

    def close(self):
        if self._fp is not None:
            self._fp.close()
            self._fp = None
   
    def next(self):
        return self.readline()
    
    def __iter__(self):
        def nextline():
            line = self.readline()
            if line:
                yield line

        return iter(nextline())

if __name__ == '__main__':
    # test
    # ar r test.ar <file1> <file2> .. <fileN>
    a = ArFile("test.ar")
    print("\n".join(a.getnames()))
