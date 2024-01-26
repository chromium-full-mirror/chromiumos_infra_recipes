# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the exoneration_util module."""

from PB.recipe_modules.chromeos.exoneration_util.exoneration_util import ExonerationUtilProperties

DEPS = [
    'recipe_engine/luci_analysis',
]


PROPERTIES = ExonerationUtilProperties
