# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/archive',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'easy',
    'gcloud',
    'tast_results',
    'util',
]

from PB.recipe_modules.chromeos.tast_exec.tast_exec import (TastExecProperties)

PROPERTIES = TastExecProperties
