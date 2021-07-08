# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_test_api

from PB.chromiumos.test.plan.source_test_plan import SourceTestPlan

Requirements = SourceTestPlan.Requirements


class CrosTestPlanV2TestApi(recipe_test_api.RecipeTestApi):

  @staticmethod
  def kernel_source_test_plan():
    return SourceTestPlan(
        requirements=Requirements(
            kernel_versions=Requirements.KernelVersions(),
        ),
    )

  @staticmethod
  def fp_source_test_plan():
    return SourceTestPlan(
        requirements=Requirements(
            fingerprint=Requirements.Fingerprint(),
        ),
    )
