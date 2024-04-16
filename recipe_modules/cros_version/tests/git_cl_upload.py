# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from PB.recipe_modules.chromeos.cros_version.tests.git_cl_upload import GitClUploadInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/cv',
    'recipe_engine/file',
    'cros_version',
]

PROPERTIES = GitClUploadInputProperties



def RunSteps(api, properties):
  api.cros_version.bump_version(properties.dry_run)


def GenTests(api):
  yield api.test(
      'ignored-exception',
      api.buildbucket.try_build(),
      api.step_data(
          'bump version.commit chromeos/config/chromeos_version.sh.create gerrit change for chromiumos/overlays/chromiumos-overlay.git_cl upload',
          retcode=1),
      api.properties(GitClUploadInputProperties(dry_run=True)),
      api.post_check(
          post_process.DoesNotRun,
          'bump version.commit chromeos/config/chromeos_version.sh.abandon CL 1',
      ),
      api.post_check(
          post_process.StepTextEquals,
          'bump version',
          'Could not `git push`. Ignoring as this is a dry-run.',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'unexpected-exception',
      api.buildbucket.try_build(),
      api.step_data(
          'bump version.commit chromeos/config/chromeos_version.sh.create gerrit change for chromiumos/overlays/chromiumos-overlay.git_cl upload',
          retcode=1),
      api.properties(GitClUploadInputProperties(dry_run=False)),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
