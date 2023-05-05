# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Any, Dict

from recipe_engine import recipe_test_api

from PB.recipe_modules.chromeos.binhost_lookup_service import (
    binhost_lookup_service as binhost_lookup_service_pb2)


class BinhostLookupServiceTestApi(recipe_test_api.RecipeTestApi):
  """Return test data for the binhost lookup service."""

  @property
  def input_properties(self) -> Dict[str, Any]:
    """Input properties for the binhost_lookup_service module."""
    return ({
        '$chromeos/binhost_lookup_service':
            binhost_lookup_service_pb2.BinhostLookupServiceProperties(
                pubsub_project_id='chromeos-prebuilts',
                pubsub_topic_id_update_snapshot_data=(
                    'test_topic_id_update_snapshot_data'))
    })
