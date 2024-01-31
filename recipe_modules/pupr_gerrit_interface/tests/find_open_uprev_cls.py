# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that find_open_uprev_cls() finds CLs as expected."""

from typing import Generator
from typing import List

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.pupr_gerrit_interface.tests.tests import \
  FindOpenUprevCLsProperties
from RECIPE_MODULES.chromeos.gerrit.api import ChangeInfo
from RECIPE_MODULES.chromeos.gerrit.api import change_info_to_gerrit_change
from RECIPE_MODULES.chromeos.pupr_gerrit_interface.api import HOSTS_REMOTES
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
    'pupr_gerrit_interface',
]


PROPERTIES = FindOpenUprevCLsProperties

CHROMIUM_HOST, CHROMIUM_REMOTE = HOSTS_REMOTES[0]
CHROME_INTERNAL_HOST, CHROME_INTERNAL_REMOTE = HOSTS_REMOTES[1]

CHROMIUM_PROJECT = ProjectInfo(name='my-chromium-project',
                               path='src/my-chromium-project/',
                               remote=CHROMIUM_REMOTE, branch='main',
                               rrev='refs/heads/main')
INTERNAL_PROJECT = ProjectInfo(name='my-internal-project',
                               path='src/my-internal-project/',
                               remote=CHROME_INTERNAL_REMOTE, branch='main',
                               rrev='refs/heads/main')

PUPR_TOPIC = 'my-topic'


def RunSteps(api: recipe_api.RecipeApi, properties: FindOpenUprevCLsProperties):
  """Run the test logic."""
  # Arrange
  projects_by_remote = api.pupr_gerrit_interface.sort_projects_by_remote(
      [CHROMIUM_PROJECT, INTERNAL_PROJECT])
  expected_gerrit_changes: List[GerritChange] = []
  for serialized in properties.expected_gerrit_changes:
    expected_gerrit_changes.append(serialized)

  # Act
  open_changes = api.pupr_gerrit_interface.find_open_uprev_cls(
      projects_by_remote, PUPR_TOPIC)

  # Assert
  api.assertions.maxDiff = None
  api.assertions.assertCountEqual(expected_gerrit_changes, open_changes)


def GenTests(api: recipe_test_api.RecipeTestApi
            ) -> Generator[recipe_test_api.TestData, None, None]:
  """Generate test cases to parameterize RunSteps."""

  def _get_query_step_name(host: str) -> str:
    """Return the name that calls gerrit.query_changes()."""
    return f'find open uprev CLs.find CLs from {host} host'

  def _get_host_url(host: str) -> str:
    """Return the URL corresponding to the given host."""
    return f'https://{host}-review.googlesource.com'

  CHROMIUM_HOST_URL = _get_host_url(CHROMIUM_HOST)
  CHROME_INTERNAL_HOST_URL = _get_host_url(CHROME_INTERNAL_HOST)

  def _create_change_info(project: ProjectInfo,
                          change_number: int) -> ChangeInfo:
    """Return a ChangeInfo for the given project."""
    return {
        'id': f'{project.name}~{project.branch}~{change_number}',
        'project': project.name,
        'branch': project.branch,
        'topic': PUPR_TOPIC,
        'change-id': 'Ideadbeef',
        'subject': 'wow, a change!',
        'status': 'OPEN',
        '_number': change_number,
        'owner': 'sundar@google.com',
    }

  CHROMIUM_CHANGE_INFO = _create_change_info(CHROMIUM_PROJECT, 123)
  INTERNAL_CHANGE_INFO = _create_change_info(INTERNAL_PROJECT, 456)
  CHROMIUM_GERRIT_CHANGE = change_info_to_gerrit_change(CHROMIUM_CHANGE_INFO,
                                                        CHROMIUM_HOST_URL)
  INTERNAL_GERRIT_CHANGE = change_info_to_gerrit_change(
      INTERNAL_CHANGE_INFO, CHROME_INTERNAL_HOST_URL)

  def _set_query_changes_response(host: str, changes: List[ChangeInfo]
                                 ) -> recipe_test_api.TestData:
    """Set the return value for gerrit.query_changes(), as called by PUpr."""
    step_name = _get_query_step_name(host)
    host_url = _get_host_url(host)
    return api.gerrit.set_query_changes_response(step_name, changes, host_url)

  yield api.test(
      'changes-in-both-remotes',
      _set_query_changes_response(CHROMIUM_HOST, [CHROMIUM_CHANGE_INFO]),
      _set_query_changes_response(CHROME_INTERNAL_HOST, [INTERNAL_CHANGE_INFO]),
      api.properties(
          FindOpenUprevCLsProperties(expected_gerrit_changes=[
              CHROMIUM_GERRIT_CHANGE, INTERNAL_GERRIT_CHANGE
          ])), api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-changes', _set_query_changes_response(CHROMIUM_HOST, []),
      _set_query_changes_response(CHROME_INTERNAL_HOST, []),
      api.properties(FindOpenUprevCLsProperties(expected_gerrit_changes=[])),
      api.post_process(post_process.DropExpectation))
