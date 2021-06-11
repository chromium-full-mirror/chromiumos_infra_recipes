# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/time',
    'build_menu',
    'cloud_pubsub',
]

from PB.recipe_modules.chromeos.build_reporting.build_reporting \
    import BuildReportingProperties

PROPERTIES = BuildReportingProperties
