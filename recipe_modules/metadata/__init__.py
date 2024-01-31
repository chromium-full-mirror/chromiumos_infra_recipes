# -*- coding: utf-8 -*-

# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.metadata.metadata import MetadataProperties


DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_build_api',
    'util',
]

PROPERTIES = MetadataProperties
