# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for software supply chain integrity SSCI program"""

from .api import CrosSsciApi as API

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/time',
    'recipe_engine/step',
    'depot_tools/gsutil',
    'cros_build_api',
    'cros_version',
]
