# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.gerrit.examples.changes_are_submittable import (
    ChangesAreSubmittableProperties)
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'gerrit',
    'repo',
]

PROPERTIES = ChangesAreSubmittableProperties


def RunSteps(api, properties):
  chrome_root = None
  if properties.chrome_root:
    chrome_root = api.path.abs_to_path(properties.chrome_root)

  chromeos_root = None
  if properties.chromeos_root:
    chromeos_root = api.path.abs_to_path(properties.chromeos_root)

  change = properties.change
  submittable = api.gerrit.changes_submittable(
      [change],
      chrome_root=chrome_root,
      chromeos_root=chromeos_root,
  )
  api.assertions.assertEqual(submittable, properties.expected)


def GenTests(api):
  change_with_project = GerritChange(
      host='chromium-review.googlesource.com',
      project='chromeos/chromite',
      change=91827,
      patchset=1,
  )

  chrome_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='chromium/src',
      change=91828,
      patchset=1,
  )

  change_no_project = GerritChange(
      host='chromium-review.googlesource.com',
      change=91829,
      patchset=1,
  )

  yield api.test(
      'basic',
      api.properties(change=change_with_project, expected=True,
                     chromeos_root='[CACHE]/chromeos_root'),
      api.repo.project_infos_step_data('check for merge conflicts', [{
          'project': 'chromeos/chromite'
      }]),
      api.post_process(
          post_process.LogContains,
          'check for merge conflicts',
          'req',
          ["'reference_repos', {'chromeos/chromite': 'src/chromeos/chromite'}"],
      ),
  )

  yield api.test(
      'not-submittable',
      api.properties(change=change_with_project, expected=False,
                     chromeos_root='[CACHE]/chromeos_root'),
      api.repo.project_infos_step_data('check for merge conflicts', [{
          'project': 'chromeos/chromite'
      }]),
      api.gerrit.simulated_changes_are_submittable(submittable=False),
      api.post_process(
          post_process.LogContains,
          'check for merge conflicts',
          'req',
          ["'reference_repos', {'chromeos/chromite': 'src/chromeos/chromite'}"],
      ),
  )

  yield api.test(
      'chrome-change',
      api.properties(
          change=chrome_change,
          chrome_root='[CACHE]/chrome_cache',
          expected=True,
      ),
      api.path.exists(api.path.cache_dir / 'chrome_cache' / 'src'),
      api.post_process(
          post_process.LogContains,
          'check for merge conflicts',
          'req',
          [
              "'reference_repos'",
              "'chromium/src': Path([CACHE], 'chrome_cache', 'src')"
          ],
      ),
  )

  yield api.test(
      'no-project',
      api.properties(change=change_no_project, expected=True),
      api.post_process(
          post_process.LogDoesNotContain,
          'check for merge conflicts',
          'req',
          ["'reference_repos'"],
      ),
  )
