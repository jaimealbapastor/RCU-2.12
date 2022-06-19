'''
display.py
This handles the display of each reMarkable model, which is most-useful
when taking screenshots.

RCU is a synchronization tool for the reMarkable Tablet.
Copyright (C) 2020  Davis Remmel

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

...

reStream was used for the RM2 framebuffer capture.
Copyright (c) 2020 Rien Maertens <Rien.Maertens@posteo.be>

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''

import log
from PySide2.QtCore import QByteArray, QBuffer, QIODevice
from PySide2.QtGui import QImage, QMatrix
import math
import gc
import ctypes


class DisplayRM:
    screenwidth = 1404
    screenheight = 1872
    realwidth = 1408
    dpi = 226
    bpp = 2
    pixformat = QImage.Format_RGB16
    portrait_size = (1404, 1872)
    devicefile = '/dev/fb0'
    
    def __init__(self, model):
        # Stores raw image buffer. The exact function that sets this may
        # vary depending upon the rM model.
        self.model = model

        # When this is invalid, the display should re-capture any
        # variables needed to grab the framebuffer (only really applies
        # to RM2).
        self.invalid_cache = True

    def get_image_portrait(self):
        return

    def get_image_landscape(self):
        return


class DisplayRM1(DisplayRM):
    def _grab_fb(self):
        out, err = self.model.run_cmd(
            'dd if={} bs=5271552 count=1'.format(type(self).devicefile),
            raw=True)
        if len(out) == 0:
            log.error('framebuffer length was 0; aborting')
            return

        raw_fb = out
        return raw_fb
        
        
        

    def get_image_portrait(self):
        # Return PNG data
        raw_fb = self._grab_fb()

        realwidth = type(self).realwidth
        width = type(self).screenwidth
        height = type(self).screenheight
        pixformat = type(self).pixformat
        
        # The copy() operation crops off the black border. Convert to
        # Gray8 to reduce saved file size.
        qimage = QImage(raw_fb, realwidth, height, pixformat).copy(
            0, 0, width, height).convertToFormat(
                QImage.Format_Grayscale8)

        # Dump as PNG
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.WriteOnly)
        qimage.save(buffer, 'PNG')
        pngdata = ba.data()

        ctypes.c_long.from_address(id(qimage)).value=1
        del qimage
        gc.collect()
        
        return pngdata

    def get_image_landscape(self):
        # Return PNG data
        # Rotate +90 deg.
        raw_fb = self._grab_fb()

        realwidth = type(self).realwidth
        width = type(self).screenwidth
        height = type(self).screenheight
        pixformat = type(self).pixformat
        
        # The copy() operation crops off the black border. Convert to
        # Gray8 to reduce saved file size.
        qimage = QImage(raw_fb, realwidth, height, pixformat).copy(
            0, 0, width, height).convertToFormat(
                QImage.Format_Grayscale8)

        center = qimage.rect().center()
        matrix = QMatrix()
        matrix.translate(center.x(), center.y())
        matrix.rotate(90)
        qimage_rot = qimage.transformed(matrix)

        # Dump as PNG
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.WriteOnly)
        qimage_rot.save(buffer, 'PNG')
        pngdata = ba.data()

        ctypes.c_long.from_address(id(qimage)).value=1
        ctypes.c_long.from_address(id(qimage_rot)).value=1
        del qimage
        del qimage_rot
        gc.collect()
        
        return pngdata


class DisplayRM2_rm2fb(DisplayRM1):    
    devicefile = '/dev/shm/swtfb.01'
    realwidth = 1404

    @classmethod
    def applies(cls, model):
        cmd = 'test -e {}; echo $?'.format(cls.devicefile)
        out, err = model.run_cmd(cmd)
        if len(err):
            log.error('problem testing for rm2fb')
            log.error(err)
            return
        out = out.strip('\n')
        if '0' == out:
            log.info('detected rm2fb')
            return True
        return False
        
    
    
class DisplayRM2(DisplayRM):
    screenwidth = 1872
    screenheight = 1404
    realwidth = 1872
    bpp = 1
    pixformat = QImage.Format_Grayscale8
    pagesize = 4096

    def _cache_memory_locations(self):
        width = type(self).realwidth
        height = type(self).screenheight
        bpp = type(self).bpp
        self.fb_size = width * height * bpp

        out, err = self.model.run_cmd('pidof xochitl')
        if len(err):
            log.error('problem getting pid of xochitl')
            log.error(e)
            return
        pid = out.strip()

        # In-memory framebuffer location is just after the noise from
        # /dev/fb0.
        out, err = self.model.run_cmd("grep -C1 '{}' /proc/{}/maps | tail -n1 | sed 's/-.*$//'".format(type(self).devicefile, pid))
        if len(err):
            log.error('problem getting address of RM2 framebuffer')
            log.error(err)
            return
        #log.info('++ memory address', out.strip())
        skip_bytes = int(out.strip(), 16) + 8
        block_size = type(self).pagesize
        fb_start = int(skip_bytes / block_size)
        self.fb_offset = skip_bytes % block_size
        fb_length = math.ceil(self.fb_size / block_size)
        
        self.capture_fb_cmd = '''dd if=/proc/{}/mem bs={} \
                                 skip={} count={} 2>/dev/null'''.format(
                                     pid, block_size,
                                     fb_start, fb_length)
        #debug
        #self.capture_fb_cmd = 'cat /tmp/framebuffer.raw'
        
        #log.info(self.capture_fb_cmd)

    def _grab_fb(self):
        if self.invalid_cache:
            self._cache_memory_locations()
        
        out, err = self.model.run_cmd(self.capture_fb_cmd, raw=True)
        if len(err):
            log.error('problem grabbing framebuffer')
            log.error(str(err))
            
        # Because the grab captured excess data (it was aligned to the
        # page size) we need to trim some off.
        raw_fb = out[self.fb_offset:][:self.fb_size]

        # debug
        if len(raw_fb) != self.fb_size:
            log.error('actual length of framebuffer data differed from actual length, aborting')
            log.info('expected length', self.fb_size)
            log.info('actual length', len(raw_fb))
            return

        return raw_fb

    def get_image_portrait(self):
        # Returns PNG data in portrait orientation

        raw_fb = self._grab_fb()
        width = type(self).realwidth
        height = type(self).screenheight
        pixformat = type(self).pixformat
        qimage = QImage(raw_fb, width, height, pixformat)
        
        # Rotate -90 deg.
        center = qimage.rect().center()
        matrix = QMatrix()
        matrix.translate(center.x(), center.y())
        matrix.rotate(-90)
        
        rotated_qi = qimage.transformed(matrix)

        # Dump as PNG
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.WriteOnly)
        rotated_qi.save(buffer, 'PNG')
        pngdata = ba.data()

        ctypes.c_long.from_address(id(qimage)).value=1
        ctypes.c_long.from_address(id(rotated_qi)).value=1
        del qimage
        del rotated_qi
        gc.collect()
        
        return pngdata

    def get_image_landscape(self):
        raw_fb = self._grab_fb()
        width = type(self).realwidth
        height = type(self).screenheight
        pixformat = type(self).pixformat
        qimage = QImage(raw_fb, width, height, pixformat)
        
        # Dump as PNG
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.WriteOnly)
        qimage.save(buffer, 'PNG')
        pngdata = ba.data()

        ctypes.c_long.from_address(id(qimage)).value=1
        del qimage
        gc.collect()
        
        return pngdata
