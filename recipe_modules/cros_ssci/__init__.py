# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for software supply chain integrity SSCI program"""

from .api import CrosSsciApi as API

DEPS = [
    'cros_build_api',
]
