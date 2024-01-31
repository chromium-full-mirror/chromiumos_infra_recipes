# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.binhost_lookup_service import (
    binhost_lookup_service as binhost_lookup_service_pb2)

DEPS = [
    'recipe_engine/buildbucket', 'recipe_engine/step', 'cloud_pubsub',
    'cros_infra_config'
]


PROPERTIES = binhost_lookup_service_pb2.BinhostLookupServiceProperties
