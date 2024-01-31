# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.metadata_json.metadata_json import MetadataJsonProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/led',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_artifacts',
    'cros_infra_config',
    'cros_source',
    'src_state',
    'test_util',
    'urls',
    'util',
]


PROPERTIES = MetadataJsonProperties
