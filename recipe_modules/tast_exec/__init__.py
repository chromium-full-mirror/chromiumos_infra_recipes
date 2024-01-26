# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the tast_exec module."""

from PB.recipe_modules.chromeos.tast_exec.tast_exec import (TastExecProperties)

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/archive',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/time',
    'easy',
    'failures',
    'gcloud',
    'git',
    'tast_results',
]


PROPERTIES = TastExecProperties
