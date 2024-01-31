# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.analysis_service.analysis_service import AnalysisServiceProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cloud_pubsub',
]


PROPERTIES = AnalysisServiceProperties
