# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the cros_cq_additional_tests module."""

from PB.recipe_modules.chromeos.cros_cq_additional_tests.cros_cq_additional_tests import CrosCQAdditionalTestsProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cros_infra_config',
    'git',
    'git_footers',
]


PROPERTIES = CrosCQAdditionalTestsProperties
