# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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
