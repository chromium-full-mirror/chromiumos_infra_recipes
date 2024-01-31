# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Generator

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'repo',
]



def RunSteps(api: RecipeApi):
  api.assertions.assertEqual(
      api.repo.version_at_least(api.properties['version']),
      api.properties['at_least'])


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  yield api.test(
      'version-at-least-true', api.properties(version='2.29', at_least=True),
      api.step_data(
          'check if repo version is at least 2.29.repo version',
          stdout=api.raw_io.output_text('''repo version v2.29-cr1
        (from https://chromium.googlesource.com/external/repo)
        (tracking refs/heads/main)
        (Tue, 23 Aug 2022 11:20:59 -0400)
 repo launcher version 2.29
        (from /b/s/w/ir/kitchen-checkout/depot_tools/repo_launcher)
        (currently at 2.29-cr1)
 repo User-Agent git-repo/2.29-cr1 (Linux) git/2.37.0.chromium.8 / Infra wrapper (infra/tools/git/linux-amd64 @ 9Ffr1NBbvM1o7hXrAfhJD6Zgiqk1pU67BXFCm969d44C) Python/3.8.10
 git 2.37.0.chromium.8 / Infra wrapper (infra/tools/git/linux-amd64 @ 9Ffr1NBbvM1o7hXrAfhJD6Zgiqk1pU67BXFCm969d44C)
 git User-Agent git/2.37.0.chromium.8 / Infra wrapper (infra/tools/git/linux-amd64 @ 9Ffr1NBbvM1o7hXrAfhJD6Zgiqk1pU67BXFCm969d44C) (Linux) git-repo/2.29-cr1
 Python 3.8.10+chromium.23 (default, Nov 11 2021, 05:59:41)
 [GCC 10.2.1 20210130 (Red Hat 10.2.1-11)]
 OS Linux 5.4.0-125-generic (#141~18.04.1-Ubuntu SMP Thu Aug 11 20:15:56 UTC 2022)
 CPU x86_64 (x86_64)
 Bug reports: https://issues.gerritcodereview.com/issues/new?component=1370071'''
                                       )),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'version-at-least-false', api.properties(version='2.30', at_least=False),
      api.step_data(
          'check if repo version is at least 2.30.repo version',
          stdout=api.raw_io.output_text('''repo version v2.29-cr1
        (from https://chromium.googlesource.com/external/repo)
        (tracking refs/heads/main)
        (Tue, 23 Aug 2022 11:20:59 -0400)
 repo launcher version 2.29
        (from /b/s/w/ir/kitchen-checkout/depot_tools/repo_launcher)
        (currently at 2.29-cr1)
 repo User-Agent git-repo/2.29-cr1 (Linux) git/2.37.0.chromium.8 / Infra wrapper (infra/tools/git/linux-amd64 @ 9Ffr1NBbvM1o7hXrAfhJD6Zgiqk1pU67BXFCm969d44C) Python/3.8.10
 git 2.37.0.chromium.8 / Infra wrapper (infra/tools/git/linux-amd64 @ 9Ffr1NBbvM1o7hXrAfhJD6Zgiqk1pU67BXFCm969d44C)
 git User-Agent git/2.37.0.chromium.8 / Infra wrapper (infra/tools/git/linux-amd64 @ 9Ffr1NBbvM1o7hXrAfhJD6Zgiqk1pU67BXFCm969d44C) (Linux) git-repo/2.29-cr1
 Python 3.8.10+chromium.23 (default, Nov 11 2021, 05:59:41)
 [GCC 10.2.1 20210130 (Red Hat 10.2.1-11)]
 OS Linux 5.4.0-125-generic (#141~18.04.1-Ubuntu SMP Thu Aug 11 20:15:56 UTC 2022)
 CPU x86_64 (x86_64)
 Bug reports: https://issues.gerritcodereview.com/issues/new?component=1370071'''
                                       )),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'version-at-least-missing-version',
      api.properties(version='2.30', at_least=False),
      api.step_data('check if repo version is at least 2.30.repo version',
                    stdout=api.raw_io.output_text('')),
      api.post_process(post_process.DropExpectation))
