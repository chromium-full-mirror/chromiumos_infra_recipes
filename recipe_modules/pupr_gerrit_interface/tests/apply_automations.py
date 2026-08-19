# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify apply_automations in pupr_gerrit_interface."""

from PB.recipes.chromeos.generator import BranchPolicy
from PB.recipes.chromeos.generator import PuprGerritAutomation
from PB.recipes.chromeos.generator import PuprGerritAutomationAction
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'gerrit',
    'pupr_gerrit_interface',
]


def RunSteps(api: recipe_api.RecipeApi):
  empty_policy = BranchPolicy()
  api.pupr_gerrit_interface.apply_automations(empty_policy, 'my-topic',
                                              branch='main')

  policy = BranchPolicy(
      gerrit_automations=[
          PuprGerritAutomation(
              conditions=['is:wip', '-label:Commit-Queue'],
              actions=[
                  PuprGerritAutomationAction(
                      name='add-reviewer',
                      parameters=['fqj@google.com'],
                  ),
              ],
          ),
          PuprGerritAutomation(
              conditions=['tag:custom'],
              actions=[
                  PuprGerritAutomationAction(
                      name='unknown-action',
                      parameters=[],
                  ),
              ],
          ),
      ],
  )
  api.pupr_gerrit_interface.apply_automations(policy, 'my-topic', branch='main')

  invalid_policy = BranchPolicy(
      gerrit_automations=[
          PuprGerritAutomation(
              conditions=['invalid_token_without_colon'],
              actions=[],
          ),
      ],
  )
  try:
    api.pupr_gerrit_interface.apply_automations(invalid_policy, 'my-topic',
                                                branch='main')
  except recipe_api.StepFailure:
    pass


def GenTests(api: recipe_test_api.RecipeTestApi):
  change_info = {
      '_number': 12345,
      'project': 'chromiumos/overlays/chromiumos-overlay',
      'work_in_progress': True,
      'messages': [],
  }
  change_info_with_reviewers = {
      '_number': 12345,
      'project': 'chromiumos/overlays/chromiumos-overlay',
      'reviewers': {
          'REVIEWER': [{
              'email': 'fqj@google.com',
          }],
      },
  }
  yield api.test(
      'basic',
      api.gerrit.set_query_changes_response(
          'apply automations.evaluate conditions: is:wip -label:Commit-Queue',
          [change_info],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'apply automations.evaluate conditions: tag:custom',
          [change_info],
          'https://chromium-review.googlesource.com',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'already-applied',
      api.gerrit.set_query_changes_response(
          'apply automations.evaluate conditions: is:wip -label:Commit-Queue',
          [change_info_with_reviewers],
          'https://chromium-review.googlesource.com',
      ),
      api.gerrit.set_query_changes_response(
          'apply automations.evaluate conditions: tag:custom',
          [change_info_with_reviewers],
          'https://chromium-review.googlesource.com',
      ),
      api.post_process(post_process.DropExpectation),
  )
