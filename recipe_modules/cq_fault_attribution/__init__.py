# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the cq_fault_attribution module."""

from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution \
import CqFaultAttributionApiProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'cros_infra_config',
    'easy',
    'failures',
    'looks_for_green',
]


PROPERTIES = CqFaultAttributionApiProperties
