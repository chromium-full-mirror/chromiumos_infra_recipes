# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for upreving libchrome"""

import re

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'build_menu',
    'cros_sdk',
    'cros_source',
    'src_state',
    'gerrit',
    'git',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'repo',
]


UPREV_COMMIT_SUBJECT_RE = re.compile(
    r'Automated commit: libchrome r([0-9]+) uprev')

PUSH_OPTION_LABEL_RE = re.compile(
    r'(Auto-Submit|Verified|Commit-Queue|Bot-Commit)([+-][12])')

OUTDATED_PATCH_INFO = 'crrev.com/c/{} ("{}")'


def RunSteps(api: RecipeApi):
  commit = api.src_state.gitiles_commit
  if not commit.project:
    commit = api.src_state.internal_manifest.as_gitiles_commit_proto

  with api.build_menu.configure_builder(missing_ok=True, commit=commit):
    # automated_uprev.py needs chroot to test emerge libchrome.
    with api.build_menu.setup_workspace_and_chroot():
      project_dir = api.cros_source.workspace_path.join(
          'src/platform/libchrome')
      with api.context(cwd=project_dir):
        project_info = api.repo.project_info()

        libchrome_revision = int(
            api.file.read_text('read libchrome BASE_VER',
                               project_dir.join('BASE_VER'),
                               test_data='123456'))

        outdated_changes = []
        with api.step.nest('identify outdated uprev commits') as presentation:
          # Get a list of all (latest patchsets of) open uprev commits (that are
          # not in CQ).
          changes = api.gerrit.query_changes(
              'https://chromium-review.googlesource.com',
              [('topic', 'libchrome-automated-uprev'), ('status', 'open'),
               ('label', 'Commit-Queue<2')],
          )
          patchsets = api.gerrit.fetch_patch_sets(changes) if changes else []

          latest_change = None
          latest_patchset = None
          for change, patchset in zip(changes, patchsets):
            m = UPREV_COMMIT_SUBJECT_RE.match(patchset.subject)
            # If subject does not match that from a bot commit, assume it is a
            # manually uploaded from a developer and should be kept.
            if not m:
              continue
            # Abandon if the uprev target is older than ToT libchrome.
            # RE guarantees m.group(1) is an int.
            if int(m.group(1)) <= libchrome_revision:
              outdated_changes.append((change, patchset))
              continue

            # Abandon if it has not been worked on (only patchset is from bot).
            # Gerrt starts patch set counter from 1.
            if patchset.patch_set == 1:
              outdated_changes.append((change, patchset))
              continue

            # If we have already found another potential latest change and it
            # was updated after this change, abandon this one.
            if latest_change and latest_patchset.updated > patchset.updated:
              outdated_changes.append((change, patchset))
            # This change is updated more recently, abandon the previous one.
            else:
              if latest_change:
                outdated_changes.append((latest_change, latest_patchset))
              latest_change = change
              latest_patchset = patchset

          presentation.properties['outdated_changes'] = [
              OUTDATED_PATCH_INFO.format(patchset.change_id, patchset.subject)
              for _, patchset in outdated_changes
          ]

        if outdated_changes and not api.build_menu.is_staging:
          with api.step.nest('abandon outdated uprev commits'):
            message = f'Outdated change automatically abandoned by {api.buildbucket.build.id}'
            message += f'; most recently updated uprev comit is crrev.com/c/{latest_patchset.change_id}.' if latest_patchset else '.'
            for change, _ in outdated_changes:
              api.gerrit.abandon_change(change, message)

        step_data = api.cros_sdk.run(
            'generate uprev commit', [
                'vpython3',
                '../platform/libchrome/libchrome_tools/developer-tools/uprev/automated_uprev.py',
                '--head',
                '--track_active',
                '--recipe',
            ], stdout=api.raw_io.output_text(add_output_log=True))
        ret = step_data.stdout.strip().splitlines()

        # only the last line is the push options; earlier lines are logs
        push_options = ret[-1] if ret else ''

        with api.step.nest('validate push options'):
          if not push_options.startswith('%'):
            raise StepFailure(
                'invalid push options ("{}"): should start with %'.format(
                    push_options))
          for option in push_options[1:].split(','):
            if not option:
              continue
            option = option.split('=')
            if option[0] not in ['r', 'topic', 'l', 'cc']:
              raise StepFailure(
                  'invalid push option ("{}"): only cc, r(eviewer), topic, '
                  'l(abel) options are allowed'.format(option))
            if option[0] == 'l' and (len(option) < 2 or
                                     not PUSH_OPTION_LABEL_RE.match(option[1])):
              raise StepFailure(
                  'invalid label-type push option ("{}"): '
                  'only Auto-Submit, Verified, Commit-Queue, Bot-Commit labels '
                  'with value are allowed'.format(option[1]))

        patchset_description = 'm=' + 'Generated_by%3A_https%3A%2F%2Fcr%2Dbuildbucket%2Eappspot%2Ecom%2Fbuild%2F{}'.format(
            api.buildbucket.build.id)

        with api.step.nest('push uprev commit'):
          api.git.push(
              project_info.remote,
              'HEAD:refs/for/main' + push_options + patchset_description,
              dry_run=api.build_menu.is_staging)


def GenTests(api: RecipeTestApi):
  test_data = {
      1: (
          {
              'change_id': 1,
              'updated': '2023-03-22 01:00:00.000000000',
              # older than (test) BASE_VER 123456; should be abandoned
              'subject': 'Automated commit: libchrome r123000 uprev',
              'patch_set': 2,
          },
          True),
      2: (
          {
              'change_id': 2,
              # Less recently updated; should be abandoned
              'updated': '2023-03-22 04:45:23.000000000',
              'subject': 'Automated commit: libchrome r124000 uprev',
              'patch_set': 5,
          },
          True),
      3: (
          {
              'change_id': 3,
              # More recently updated; should be kept
              'updated': '2023-03-23 12:34:56.000000000',
              'subject': 'Automated commit: libchrome r124000 uprev',
              'patch_set': 2,
          },
          False),
      4: (
          {
              'change_id': 4,
              # Less recently updated; should be abandoned
              'updated': '2023-03-23 11:22:33.000000000',
              'subject': 'Automated commit: libchrome r125000 uprev',
              'patch_set': 2,
          },
          True),
      5: (
          {
              'change_id': 5,
              'updated': '2023-03-22 01:02:03.000000000',
              'subject': 'Automated commit: libchrome r126000 uprev',
              # No manual update; should be abandoned
              'patch_set': 1,
              # gerrit/test_api bug: not setting patch_set number correctly, it is still
              # abandoned now due to older than change 3.
          },
          True),
      6: (
          {
              'change_id': 6,
              'updated': '2023-03-18 16:24:03.000000000',
              # Does not match uprev commit regex; should be kept
              'subject': 'Fix build error caused by r111111 uprev',
              'patch_set': 3,
          },
          False),
  }

  gerrit_patchset_dicts = {i: value for i, (value, _) in test_data.items()}

  gerrit_change_infos = [{
      '_number': i,
      'change': i,
      'change_number': i,
      'project': 'chromiumos/platform/libchrome',
      'host': 'chromium-review.googlesource.com',
  } for i, _ in gerrit_patchset_dicts.items()]

  gerrit_changes = [
      GerritChange(change=i, host='chromium-review.googlesource.com',
                   patchset=value['patch_set'])
      for i, value in gerrit_patchset_dicts.items()
  ]

  expected_outdated_changes = [
      OUTDATED_PATCH_INFO.format(i, value['subject'])
      for i, (value, should_abandon) in test_data.items()
      if should_abandon
  ]

  yield api.test(
      'no-active-uprev-commit',
      api.gerrit.set_query_changes_response(
          'identify outdated uprev commits', [],
          'https://chromium-review.googlesource.com'),
      api.post_check(post_process.DoesNotRun, 'abandon outdated uprev commits'),
      status='FAILURE',
  )

  yield api.test(
      'abandon-pre-ToT-uprev-commit',
      api.gerrit.set_query_changes_response(
          'identify outdated uprev commits', gerrit_change_infos,
          'https://chromium-review.googlesource.com'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify outdated uprev commits', gerrit_changes,
          gerrit_patchset_dicts),
      *[
          api.post_check(
              (post_process.MustRun
               if should_abandon else post_process.DoesNotRun),
              f'abandon outdated uprev commits.abandon CL {i}.gerrit abandon')
          for i, (_, should_abandon) in test_data.items()
      ],
      status='FAILURE',
  )

  yield api.test(
      'abandon-pre-ToT-uprev-commit-staging',
      api.buildbucket.generic_build(builder='staging-libchrome-uprev',
                                    bucket='staging'),
      api.gerrit.set_query_changes_response(
          'identify outdated uprev commits', gerrit_change_infos,
          'https://chromium-review.googlesource.com'),
      api.gerrit.set_gerrit_fetch_changes_response(
          'identify outdated uprev commits', gerrit_changes,
          gerrit_patchset_dicts),
      api.post_check(post_process.PropertyEquals, 'outdated_changes',
                     expected_outdated_changes),
      status='FAILURE',
  )

  yield api.test(
      'script-success',
      api.gerrit.set_query_changes_response(
          'identify outdated uprev commits', [],
          'https://chromium-review.googlesource.com'),
      api.step_data(
          'generate uprev commit', stdout=api.raw_io.output_text(
              '%r=fqj@google.com,r=hidehiko@google.com,'
              'topic=libchrome-automated-uprev,l=Auto-Submit+1,l=Verified+1,')),
  )

  yield api.test(
      'script-wrong-option-format',
      api.gerrit.set_query_changes_response(
          'identify outdated uprev commits', [],
          'https://chromium-review.googlesource.com'),
      api.step_data(
          'generate uprev commit', stdout=api.raw_io.output_text(
              'r=fqj@google.com,r=hidehiko@google.com,'
              'topic=libchrome-automated-uprev,l=Auto-Submit+1,l=Verified+1,')),
      api.post_check(post_process.StepFailure, 'validate push options'),
      status='FAILURE',
  )

  yield api.test(
      'script-invalid-option',
      api.gerrit.set_query_changes_response(
          'identify outdated uprev commits', [],
          'https://chromium-review.googlesource.com'),
      api.step_data(
          'generate uprev commit', stdout=api.raw_io.output_text(
              '%submit,r=fqj@google.com,r=hidehiko@google.com,'
              'topic=libchrome-automated-uprev,l=Auto-Submit+1,l=Verified+1,')),
      api.post_check(post_process.StepFailure, 'validate push options'),
      status='FAILURE',
  )

  yield api.test(
      'script-invalid-label',
      api.gerrit.set_query_changes_response(
          'identify outdated uprev commits', [],
          'https://chromium-review.googlesource.com'),
      api.step_data(
          'generate uprev commit', stdout=api.raw_io.output_text(
              '%r=fqj@google.com,r=hidehiko@google.com,'
              'topic=libchrome-automated-uprev,'
              'l=Auto-Submit+1,l=Verified+1,l=Code-Review+1,')),
      api.post_check(post_process.StepFailure, 'validate push options'),
      status='FAILURE',
  )
