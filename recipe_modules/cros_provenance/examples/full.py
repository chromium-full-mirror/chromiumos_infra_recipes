# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ["recipe_engine/properties", "recipe_engine/step", "cros_provenance"]

from PB.recipe_modules.chromeos.cros_provenance.cros_provenance import (
    ProvenanceProperties,)


def RunSteps(api):
  api.cros_provenance.generate_provenance(["path/to/artifact"], "test_recipe")


def GenTests(api):
  yield api.test(
      "basic", api.properties(ProvenanceProperties(key_path="path/to/kms/key")))
