# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Simple script for finding free ssh port."""

import socket

sock = socket.socket()
sock.bind(('localhost', 0))
_, port = sock.getsockname()
sock.close()

print(port)
