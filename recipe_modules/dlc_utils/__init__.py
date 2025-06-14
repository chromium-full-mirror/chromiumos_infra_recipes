# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helper recipe module for managing DLCs in ChromeOS.

Provides utility functions to handle operations around Downloadable Content (DLCs),
such as listing available DLCs in a path (local or GS), retrieving DLC artifact
locations and corresponding file hashes, and copying prebuilt DLCs to a specified
bucket.
"""
from PB.recipe_modules.chromeos.dlc_utils.dlc_utils import (DlcUtilsProperties)

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_build_api',
    'future_utils',
    'gcloud',
]


PROPERTIES = DlcUtilsProperties
