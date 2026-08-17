# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that uprev_version_file() creates local uprev commits as expected."""

import json
from typing import Generator

from PB.chromite.api import packages as packages_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos import generator as generator_pb2
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData
from RECIPE_MODULES.chromeos.pupr_local_uprev.api import LocalUprevConfig

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_build_api',
    'cros_source',
    'gerrit',
    'git',
    'pupr_local_uprev',
    'repo',
    'test_util',
]

FILE_PATHS = ['chrome/src/chromeos/CHROMEOS_LKGM']
TOPIC = 'chromeos-lkgm'
VERSIONS = [
    packages_pb2.UprevVersionFileRequest.GitRef(
        repository='/chromeos/manifest-internal',
        ref='refs/heads/snapshot',
        revision='50a00e4166dc7fca08f026792b8d53f751d536b7',
    )
]


def RunSteps(api: RecipeApi):
  # Arrange
  api.pupr_local_uprev.set_generator_config(
      LocalUprevConfig.for_test(
          uprev_target_kind=generator_pb2.UprevTargetKind.VERSION_FILE,
          version_files=FILE_PATHS,
          allow_partial_uprev=api.properties.get('allow_partial_uprev', False),
      ))

  # Act
  ebuilds_by_project = api.pupr_local_uprev.uprev_version_files(VERSIONS, TOPIC)

  # Assert
  expect_none_response = api.properties.get('expect_none_response', False)
  if expect_none_response:
    api.assertions.assertIsNone(ebuilds_by_project)
  else:
    api.assertions.assertIsNotNone(ebuilds_by_project)

  # Also test rebase_cl for coverage
  if api.properties.get('test_rebase', False):
    open_changes = [
        GerritChange(host='chromium-review.googlesource.com', change=1234)
    ]
    api.pupr_local_uprev.rebase_cl(open_changes, TOPIC, 1234)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Specific test cases on uprev_version_file()"""

  def _with_repo_infos(name, *args, **kwargs) -> TestData:
    """Create a test case that mocks repo project infos."""
    return api.test(
        name,
        api.step_data(
            'try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
            '.read output file',
            api.file.read_raw(
                content=json.dumps({
                    'responses': [{
                        'version':
                            '16626.0.0-1076201',
                        'modified_files':
                            ['[START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM']
                    }]
                }))),
        *args,
        **kwargs,
    )

  def _with_repo_project_infos(name, *args, **kwargs) -> TestData:
    """Create a test case that mocks repo project infos."""
    return api.test(
        name,
        api.step_data(
            'try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
            '.read output file',
            api.file.read_raw(
                content=json.dumps({
                    'responses': [{
                        'version':
                            '16626.0.0-1076201',
                        'modified_files': [
                            '[START_DIR]/chromiumos_workspace/src/overlay/modified_file'
                        ]
                    }]
                }))),
        api.repo.project_infos_step_data('commit uprev', data=[
            {
                'project': 'src/overlay'
            },
        ], iteration=1),
        *args,
        **kwargs,
    )

  yield _with_repo_infos(
      'basic',
      api.git.diff_check(True),
      api.step_data(
          'commit uprev.commit in chrome.git remote',
          api.raw_io.stream_output_text(
              'https://chromium.googlesource.com/a/chromium/src.git')),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_process(post_process.DropExpectation),
  )

  yield _with_repo_project_infos(
      'repo-file',
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'additional-commit-info',
      api.step_data(
          'try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
          '.read output file',
          api.file.read_raw(
              content=json.dumps({
                  'responses': [{
                      'version': '16626.0.0-1076201',
                      'modified_files':
                          ['[START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM'],
                      'additional_commit_info': 'Extra details about LKGM uprev'
                  }]
              }))),
      api.git.diff_check(True),
      api.step_data(
          'commit uprev.commit in chrome.git remote',
          api.raw_io.stream_output_text(
              'https://chromium.googlesource.com/a/chromium/src.git')),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_check(
          post_process.StepCommandRE,
          'commit uprev.commit in chrome.write commit message',
          [
              '.*', '.*', '.*', '.*', '.*', '.*',
              r'(?s).*\n\nExtra details about LKGM uprev\n.*', '.*'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'repo-file-additional-commit-info',
      api.step_data(
          'try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
          '.read output file',
          api.file.read_raw(
              content=json.dumps({
                  'responses': [{
                      'version':
                          '16626.0.0-1076201',
                      'modified_files': [
                          '[START_DIR]/chromiumos_workspace/src/overlay/modified_file'
                      ],
                      'additional_commit_info':
                          'Extra details about repo file uprev'
                  }]
              }))),
      api.repo.project_infos_step_data('commit uprev', data=[
          {
              'project': 'src/overlay'
          },
      ], iteration=1),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'commit uprev'),
      api.post_check(
          post_process.StepCommandRE,
          'commit uprev.commit in overlay.write commit message',
          [
              '.*', '.*', '.*', '.*', '.*', '.*',
              r'(?s).*\n\nExtra details about repo file uprev\n.*', '.*'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  # No changes detected
  yield api.test(
      'no-uprev-change',
      api.properties(expect_none_response=True),
      api.step_data(
          'try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
          '.read output file',
          api.file.read_raw(
              content='{"responses": [{"version": "16626.0.0-1076201", "modified_files": ["[START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM"]}]}'
          )),
      api.git.diff_check(False),
      api.post_check(post_process.DoesNotRun, 'commit uprev'),
      api.post_process(post_process.DropExpectation),
  )

  # No responses returned from Build API
  yield api.test(
      'no-uprev-response',
      api.properties(expect_none_response=True),
      api.post_check(post_process.DoesNotRun, 'commit uprev'),
      api.step_data(
          'try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
          '.read output file', api.file.read_raw(content='{}')),
      api.post_process(post_process.DropExpectation),
  )

  # Test rebase_cl
  yield _with_repo_infos(
      'rebase',
      api.properties(test_rebase=True),
      api.git.diff_check(True),
      api.step_data('rebase CL 1234.commit uprev.git branch',
                    api.raw_io.stream_output_text('  pupr\n* main')),
      api.step_data(
          'rebase CL 1234.try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
          '.read output file',
          api.file.read_raw(
              content='{"responses": [{"version": "16626.0.0-1076201", "modified_files": ["[START_DIR]/chrome/src/chromeos/CHROMEOS_LKGM"]}]}'
          )),
      api.gerrit.set_gerrit_fetch_changes_response(
          'rebase CL 1234.get CL 1234 description',
          [GerritChange(host='chromium-review.googlesource.com', change=1234)],
          {
              1234: {
                  'change_id': 1234,
                  'created': '2020-10-22 18:54:00.000000000',
                  'messages': [],
                  'revision_info': {
                      'ref': 'refs/change/foo',
                      'commit': {
                          'message':
                              'Cool commit message.\n\nPupr-Upstream-Versions: [{"ref": "refs/heads/snapshot", "repository": "/chromeos/manifest-internal", "revision": "50a00e4166dc7fca08f026792b8d53f751d536b7"}]\nChange-Id: deadbeef\n',
                      },
                  },
              }
          },
      ),
      api.post_check(post_process.MustRun, 'rebase CL 1234'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'allow-partial-uprev-no-changes',
      api.properties(
          allow_partial_uprev=True,
          expect_none_response=True,
      ),
      api.step_data(
          'try uprev chrome/src/chromeos/CHROMEOS_LKGM.uprev version file'
          '.read output file',
          api.file.read_raw(
              content='{"responses": [{"version": "16626.0.0-1076201", "modified_files": ["[START_DIR]/chromiumos_workspace/chrome/src/chromeos/CHROMEOS_LKGM"]}]}'
          )),
      api.git.diff_check(False),
      api.post_check(post_process.DoesNotRun, 'commit uprev'),
      api.post_process(post_process.DropExpectation),
  )
