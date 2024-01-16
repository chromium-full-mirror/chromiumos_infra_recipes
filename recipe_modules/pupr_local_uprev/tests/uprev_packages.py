# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that uprev_packages() creates local uprev commits as expected."""

from typing import Generator

from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.pupr_local_uprev.tests.uprev_packages import \
  UprevPackagesProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_build_api',
    'cros_source',
    'git',
    'pupr_local_uprev',
    'repo',
    'test_util',
]

PROPERTIES = UprevPackagesProperties

BUILD_TARGETS = [BuildTarget(name='build-target')]
PACKAGE_CHROME = PackageInfo(category='chromeos-base',
                             package_name='chromeos-chrome')
PACKAGE_LACROS = PackageInfo(category='chromeos-base',
                             package_name='chromeos-lacros')
PACKAGES = [PACKAGE_CHROME, PACKAGE_LACROS]
TOPIC = 'cool_topic'
VERSIONS = [UprevVersionedPackageRequest.GitRef()]


def RunSteps(api: RecipeApi, properties: UprevPackagesProperties):
  # Arrange
  api.pupr_local_uprev.set_generator_attributes(
      additional_commit_message=properties.additional_commit_message,
      additional_commit_footer=properties.additional_commit_footer,
      allow_partial_uprev=properties.allow_partial_uprev,
      packages=PACKAGES,
      build_targets=BUILD_TARGETS,
  )

  # Act
  ebuilds_by_project = api.pupr_local_uprev.uprev_packages(VERSIONS, TOPIC)

  # Assert
  if properties.expect_none_response:
    api.assertions.assertIsNone(ebuilds_by_project)
  else:
    api.assertions.assertIsNotNone(ebuilds_by_project)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Specific test cases on uprev_packages()"""

  def _with_repo_infos(name, *args, **kwargs) -> TestData:
    """Create a test case that mocks repo project infos."""
    return api.test(
        name,
        api.repo.project_infos_step_data('commit uprev', data=[
            {
                'project': 'overlay'
            },
        ], iteration=1),
        api.repo.project_infos_step_data(
            'commit uprev', data=[
                {
                    'project': 'private-overlay',
                    'remote': 'cros-internal'
                },
            ], iteration=2), *args, **kwargs)

  yield _with_repo_infos(
      'basic',
      api.properties(
          expect_none_response=False,
      ),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_process(post_process.DropExpectation),
  )

  # Because of the api.git.diff_check, the uprev looks like a no-op.
  yield api.test(
      'no-uprev-change',
      api.properties(
          expect_none_response=True,
      ),
      api.git.diff_check(False),
      api.post_check(post_process.DoesNotRun, 'commit uprev'),
      api.post_process(post_process.DropExpectation),
  )

  # The git step data spoofs an uprev for one package, but not the other.
  # Because we don't set allow_partial_uprev, the uprev should terminate.
  yield api.test(
      'forbid-partial-uprev',
      api.properties(
          expect_none_response=True,
      ),
      api.git.step_data(
          'try uprev chromeos-base/chromeos-chrome.verify updates.diff check.git diff',
          retcode=True),
      api.git.step_data(
          'try uprev chromeos-base/chromeos-lacros.verify updates.diff check.git diff',
          retcode=False),
      api.post_check(post_process.DoesNotRun, 'commit uprev'),
      api.post_process(post_process.DropExpectation),
  )

  # The git step data spoofs an uprev for one package, but not the other.
  # Because we set allow_partial_uprev=True, the uprev should continue.
  yield _with_repo_infos(
      'allow-partial-uprev',
      api.properties(
          allow_partial_uprev=True,
          expect_none_response=False,
      ),
      api.git.step_data(
          'try uprev chromeos-base/chromeos-chrome.verify updates.diff check.git diff',
          retcode=True),
      api.git.step_data(
          'try uprev chromeos-base/chromeos-lacros.verify updates.diff check.git diff',
          retcode=False),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_process(post_process.DropExpectation),
  )

  # The git.diff_check will always show no change.
  # Because we set allow_partial_uprev=True, we'll check every
  # package before returning.
  yield api.test(
      'allow-partial-uprev-no-changes',
      api.properties(
          allow_partial_uprev=True,
          expect_none_response=True,
      ),
      api.git.diff_check(False),
      api.post_check(post_process.DoesNotRun, 'commit uprev'),
      api.post_process(post_process.DropExpectation),
  )

  yield _with_repo_infos(
      'additional-commit-message',
      api.properties(
          additional_commit_message='TEST',
      ),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_check(
          post_process.StepCommandRE,
          'commit uprev.commit in overlay.write commit message',
          ['.*', '.*', '.*', '.*', '.*', '.*', r'(?s).*\n\nTEST\n.*', '.*']),
      api.post_process(post_process.DropExpectation),
  )

  yield _with_repo_infos(
      'additional-commit-footer',
      api.properties(
          additional_commit_footer='Cq-Footer: TEST',
      ),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_check(
          post_process.StepCommandRE,
          'commit uprev.commit in overlay.write commit message', [
              '.*', '.*', '.*', '.*', '.*', '.*',
              r'(?s).*\nCq-Cl-Tag: pupr:cool_topic\nCq-Footer: TEST\n$', '.*'
          ]),
      api.post_process(post_process.DropExpectation),
  )

  # The BuildAPI call to PackageService.UprevVersionedPackage will return {}.
  yield api.test(
      'no-uprev-response',
      api.properties(expect_none_response=True),
      api.post_check(post_process.DoesNotRun, 'commit uprev'),
      api.step_data(
          'try uprev chromeos-base/chromeos-chrome.uprev versioned package'
          '.read output file', api.file.read_raw(content='{}')),
      api.post_process(post_process.DropExpectation),
  )

  yield _with_repo_infos(
      'with-gerrit-changes',
      api.git.diff_check(True),
      api.test_util.test_build(
          revision=None, extra_changes=[
              GerritChange(host='chromium-review.googlesource.com', change=1234)
          ], created_by='user:lamontjones@chromium.org').build,
      api.post_process(post_process.DropExpectation),
  )
