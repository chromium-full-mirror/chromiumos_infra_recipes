# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cloud_pubsub',
]

from PB.recipe_modules.chromeos.analysis_service.analysis_service import (
    AnalysisServiceProperties)

PROPERTIES = AnalysisServiceProperties
