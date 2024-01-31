# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_som.cros_som import CrosSomProperties

DEPS = [
    'recipe_engine/step', 'recipe_engine/service_account', 'recipe_engine/time',
    'recipe_engine/url', 'support'
]


PROPERTIES = CrosSomProperties
