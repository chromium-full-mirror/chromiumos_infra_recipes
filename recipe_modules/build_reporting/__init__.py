# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cloud_pubsub',
    'cros_signing',
    'cros_tags',
]

from PB.recipe_modules.chromeos.build_reporting.build_reporting \
    import BuildReportingProperties

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = BuildReportingProperties
