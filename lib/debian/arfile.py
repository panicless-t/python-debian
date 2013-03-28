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
import copy
from tarfile import copyfileobj

BSD_FORMAT = 0
GNU_FORMAT = 1
DEFAULT_FORMAT = BSD_FORMAT

GLOBAL_HEADER = b"!<arch>\n"
GLOBAL_HEADER_LENGTH = len(GLOBAL_HEADER)

FILE_HEADER_LENGTH = 60
FILE_MAGIC = b"`\n"

class ArError(Exception):
    pass

def clean_fn(fn):
    return fn.rstrip().split(b"/")[0]

class ArMember(object):
    """ Member of an ar archive.

    Implements most of a file object interface: read, readline, next,
    readlines, seek, tell, close.
    
    ArMember objects have the following (read-only) properties:
        - name      member name in an ar archive
        - format    file format (BSD/GNU)
        - mtime     modification time
        - owner     owner user
        - group     owner group
        - fmode     file permissions
        - size      size in bytes
        - arfile    ArFile instance this member belongs to"""

    def __init__(self, name=''):
        self.name = name      # member name (i.e. filename) in the archive
        self._endslash = 0    # member name had trailing slash
        self.mtime = 0        # last modification time
        self.owner = 0        # owner user
        self.group = 0        # owner group
        self.fmode = 0o644    # permissions
        self.size = 0         # member size in bytes
        self.arfile = None    # file name associated with this member
        self._offset = 0      # start-of-data offset
        self._end = 0         # end-of-data offset
        self.mode = None      # file open mode
        self._seekpos = 0     # seek position within archived file
        self._closed = False  # if this file is closed

    @classmethod
    def from_buf(cls, buf, arfile, offset, encoding=None, errors=None, mode='rb'):
        """ Construct a ArInfo object from a 60-byte header"""
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

        obj = cls()
        obj.arfile = arfile
        obj._endslash = int(buf[0:16].rstrip().endswith(b"/") or buf[0] == b'/')
        obj.size  = int(buf[48:58])
        obj._offset = offset # start-of-data
        obj._end  = obj._offset + obj.size
        if obj._endslash:
            if buf[0:16].rstrip() == b'//':
                # this is the long filename mapping data
                obj.seek(0)
                arfile._parse_long_fn(obj.read())
                return False
        obj._parse_name(buf[0:16])
        if sys.version >= '3':
            obj.name = obj.name.decode(encoding, errors)
        obj.mtime = int(buf[16:28])
        obj.owner = int(buf[28:34])
        obj.group = int(buf[34:40])
        obj.fmode = buf[40:48]  # XXX octal value

        obj.mode  = mode
        return obj

    @classmethod
    def from_arfile(cls, fp, arfile, encoding=None, errors=None, mode='rb'):
        """fp is an open File object positioned on a valid file header inside
        an ar archive. Return a new ArMember on success, None otherwise. """
        # FIXME: Mode should probably not be in last position.
        buf = fp.read(FILE_HEADER_LENGTH)
        return cls.from_buf(buf, arfile, encoding=encoding, errors=errors, mode=mode, offset=fp.tell())

    # file interface

    # XXX this is not a sequence like file objects
    def _ensure_open(self):
        """used to ensure the file is open FIXME: this should probably go out"""
        if self.arfile._fileobj is None:
            raise IOError('I/O operation on closed file')

    def _parse_name(self, name):
        """Parse filenames and optionally look them up in long filename mapping.
        """
        if self.arfile.format == None:
            if name.startswith(b'/') or name.strip().endswith(b'/'):
                self.arfile.format = GNU_FORMAT
            else:
                self.arfile.format = BSD_FORMAT

        if self.arfile.format == GNU_FORMAT:
            self._endslash = 1
            if name.startswith(b'/'):
                # This is a long file name. In GNU long file name format, the
                # long filenames are stored in an special filename named `//',
                # and identified by the offset of that file. E.g. `/30' means
                # the filename starts at 30 bytes into file `//' and runs until
                # next newline.
                long_fn_index = int(name.decode(self.arfile.encoding).split('/', 1)[1].strip())
                clean_name = clean_fn(self.arfile._longfn_map[long_fn_index])
            else:
                clean_name = clean_fn(name)
        elif self.arfile.format == BSD_FORMAT:
            self._endslash = 0
            if name.startswith(b'#1/'):
                # This is BSD style long name extension. In this file format,
                # the long file names are stored as an appendix to file header
                # (and prefix to file contents. The header of a long file name
                # can be idenfied by starting `#1/', following by length of file
                # name appendix. E.g. `#1/30' means the filename starts right
                # after the header and runs for 30 bytes.
                long_fn_length = int(name[3:].strip())
                lfn = self.arfile._fileobj.read(long_fn_length)
                clean_name = clean_fn(lfn)
                self._offset += long_fn_length
                self.size += -long_fn_length
                self._seekpos = 0
            else:
                clean_name = clean_fn(name)
        else:
            raise NotImplementedError
        self.name = clean_name

    def getheader(self):
        """Returns the header bytes used to add member to archive."""
        name = self.name
        
        if self.arfile._endslash:
            name += '/'
        name = name.encode(self.arfile.encoding)
        if len(name) > 16:
            raise NotImplementedError('Long file names are not supported')
        name = name + b' '*(16-len(name))
        rest = ('{0.mtime: <9}  {0.owner: <5} {0.group: <5} {0.fmode: <7} {0.size: <10}`\n'.format(self)).encode(self.arfile.encoding)
        return name + rest

    def getpadding(self):
        """Returns the padding byte if needed."""
        if self.size % 2 == 1:
            return b'\n'
        return b''

    def read(self, size=0):
        self._ensure_open()
        self.seek(self._seekpos)
        if size > 0 and size <= self._end - self._offset - self._seekpos: # there's room
            self.arfile._fileobj.seek(self._offset + self._seekpos)
            buf = self.arfile._fileobj.read(size)
            self._seekpos += len(buf)
            return buf

        if self._offset + self._seekpos >= self._end or self._offset + self._seekpos < self._offset:
            return b''
        buf = self.arfile._fileobj.read(self._end - self._offset - self._seekpos)
        self._seekpos += len(buf)
        return buf

    def readline(self, size=None):
        self._ensure_open()

        self.seek(self._seekpos)
        if size is not None:
            buf = self.arfile._fileobj.readline(size)
        else:
            buf = self.arfile._fileobj.readline()
        self._seekpos += len(buf)
        if self._offset + self._seekpos > self._end:
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
        if self.arfile._fileobj.tell() < self._offset:
            self.arfile._fileobj.seek(self._offset)

        if whence < 2 and offset + self.arfile._fileobj.tell() < self._offset:
            raise IOError("Can't seek at %d" % offset)

        if whence == 1:
            self.arfile._fileobj.seek(offset, 1)
        elif whence == 0:
            self.arfile._fileobj.seek(self._offset + offset, 0)
        elif whence == 2:
            self.arfile._fileobj.seek(self._end + offset, 0)
        self._seekpos = self.arfile._fileobj.tell() - self._offset

    def tell(self):
        return self._seekpos

    def _tell(self):
        self._ensure_open()
        cur = self.arfile._fileobj.tell()

        if cur < self._offset:
            return 0
        else:
            return cur - self._offset

    def seekable(self):
        return True

    def close(self):
        pass

    def next(self):
        return self.readline()

    def __iter__(self):
        def nextline():
            line = self.readline()
            if line:
                yield line

        return iter(nextline())


class ArFile(object):
    """ Representation of an ar archive, see man 1 ar.
    
    The interface of this class tries to mimick that of the TarFile module in
    the standard library.
    
    ArFile objects have the following (read-only) properties:
        - members       same as getmembers()
    """

    armember = ArMember

    def __init__(self, filename=None, mode='r', fileobj=None,
                 encoding=None, errors=None, format=None):
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
        self.format = format
        self._endslash = None
        self._modemap = {'r': 'rb', 'a': 'r+b', 'w': 'r+b'}
        self._longfn_map = {}

        if encoding is None:
            encoding = sys.getfilesystemencoding()
        self.encoding = encoding
        if errors is None:
            if sys.version >= '3.2':
                errors = 'surrogateescape'
            else:
                errors = 'strict'
        self.errors = errors
        self.mode = mode
        if self.mode in 'ra':
            self._index_archive()
        elif self.mode == 'w':
            self._truncate_archive()
        else:
            raise ValueError("Invalid open mode; must be 'r', 'a' or 'w'.")

    def _index_archive(self):
        if self.name:
            fp = self._fileobj = open(self.name, self._modemap[self.mode])
        elif self._fileobj:
            fp = self._fileobj
        else:
            raise ArError("Unable to open valid file")
        if fp.read(GLOBAL_HEADER_LENGTH) != GLOBAL_HEADER:
            raise ArError("Unable to find global header")

        while True:
            newmember = self.armember.from_arfile(fp, self,
                                           encoding=self.encoding,
                                           errors=self.errors,
                                           mode=self.mode)
            if newmember is None:
                break
            if newmember is False:
                continue
            if self._endslash is None:
                self._endslash = newmember._endslash
            self.members.append(newmember)
            if self.members[0]._endslash != newmember._endslash:
                raise ValueError("BSD/GNU filename field format mixup.")
            self.members_dict[newmember.name] = newmember
            if newmember.size % 2 == 0: # even, no padding
                fp.seek(newmember._end, 0) # skip to next header
            else:
                fp.seek(newmember._end + 1 , 0) # skip to next header

    def _truncate_archive(self):
        if self.name:
            fp = self._fileobj = open(self.name, 'wb')
        elif self._fileobj:
            fp = self._fileobj
        else:
            raise IOError("Invalid parameters passed, need to specify either filename or fileobj")
        fp.write(GLOBAL_HEADER)
        fp.flush()

    def _ensure_open(self):
        if not self._fileobj:
            self._fileobj = open(self.name, self._modemap[self.mode])

    def _parse_long_fn(self, data):
        """Parses long filename mapping
        """
        pos = 0
        nextlf = data.find(b'\n', pos)
        while nextlf > -1:
            fn = data[pos:nextlf+1]
            self._longfn_map[pos] = fn
            pos = nextlf + 1
            nextlf = data.find(b'\n', pos)

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
        copyfileobj(m, fd, m.size)
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
            if isinstance(member, self.armember) and m.name == member.name:
                return m
            elif member == m.name:
                return m
        return None

    def getarmember(self, name=None, fileobj=None):
        """Create a ArInfo object for either the file `name' or the file
           object`fileobj' (osing os.fstat on its file descriptor). You can
           modify some of the TarInfo's attributes before you add it using
           addfile().
        """

        # When fileobj is given, replace name by
        # fileobj's real name.
        if fileobj is not None:
            name = fileobj.name
        
        armember = self.armember()
        armember.arfile = self
        
        if fileobj is None:
            st = os.stat(name)
        else:
            st = os.fstat(fileobj.fileno())
        
        armember.name = name
        armember._endslash = self._endslash
        armember.mtime = int(st.st_mtime)
        armember.owner = int(st.st_uid)
        armember.group = int(st.st_gid)
        armember.fmode = '%o' % st.st_mode
        armember.size = st.st_size
        return armember

    def add(self, name):
        member = self.getarmember(name)
        self._addfile(member)

    def addfile(self, armember, fileobj=None):
        return self._addfile(armember, fileobj=fileobj)

    def _addfile(self, armember, fileobj=None):
        if self.mode == 'r':
            raise IOError("File not open for writing")
        armember = copy.copy(armember)
        hdr = armember.getheader()
        assert len(hdr) == 60, "Invalid header length"
        self._fileobj.write(hdr)
        if fileobj is None:
            fileobj = open(armember.name, 'rb')
        copyfileobj(fileobj, self._fileobj, armember.size)
        self._fileobj.write(armember.getpadding())
        self.members.append(armember)
        self.members_dict[armember.name] = armember

    def close(self):
        self._fileobj.close()

    def __iter__(self):
        """ Iterate over the members of the present ar archive. """

        return iter(self.__members)

    def __getitem__(self, name):
        """ Same as .getmember(name). """

        return self.getmember(name)

if __name__ == '__main__':
    # test
    # ar r test.ar <file1> <file2> .. <fileN>
    a = ArFile("test.ar")
    print("\n".join(a.getnames()))
