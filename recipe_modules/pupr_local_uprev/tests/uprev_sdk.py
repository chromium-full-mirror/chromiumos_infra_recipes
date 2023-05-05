# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that uprev_sdk() creates local uprev commits as expected."""

from typing import Generator

from PB.recipe_modules.chromeos.pupr_local_uprev import pupr_local_uprev
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'pupr_local_uprev',
]


def RunSteps(api: RecipeApi):
  """Main test case logic."""
  api.pupr_local_uprev.uprev_sdk()


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Specific test cases on uprev_sdk().

  TODO(b/259445565): Once uprev_sdk() has been implemented, flesh this out.
  """
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/pupr_local_uprev':
                  pupr_local_uprev.PuprLocalUprevProperties(
                      sdk_uprev_spec=pupr_local_uprev.SdkUprevSpec(
                          sdk_version='2023.03.14.159265',
                          toolchain_template='2023/03/%(target)s-2023.03.14.159265.tar.xz',
                      ),
                  ),
          }),
      api.post_check(
          post_process.StepSuccess,
          'uprev sdk.validate SDK uprev spec',
      ),
  )

  yield api.test(
      'no-sdk-version',
      api.properties(
          **{
              '$chromeos/pupr_local_uprev':
                  pupr_local_uprev.PuprLocalUprevProperties(
                      sdk_uprev_spec=pupr_local_uprev.SdkUprevSpec(
                          toolchain_template='2023/03/%(target)s-2023.03.14.159265.tar.xz',
                      ),
                  ),
          }),
      api.post_check(
          post_process.StepException,
          'uprev sdk.validate SDK uprev spec',
      ),
      api.post_check(post_process.SummaryMarkdown, 'No SDK version specified.'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'no-toolchain-template',
      api.properties(
          **{
              '$chromeos/pupr_local_uprev':
                  pupr_local_uprev.PuprLocalUprevProperties(
                      sdk_uprev_spec=pupr_local_uprev.SdkUprevSpec(
                          sdk_version='2023.03.14.159265',
                      ),
                  ),
          }),
      api.post_check(
          post_process.StepException,
          'uprev sdk.validate SDK uprev spec',
      ),
      api.post_check(
          post_process.SummaryMarkdown,
          'No toolchain template specified.',
      ),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
