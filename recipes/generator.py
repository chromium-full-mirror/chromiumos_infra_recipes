# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the PUpr generator.

PUpr is a general uprev pipeline that listens for package releases (via LUCI
Scheduler gitiles triggers), generates ebuild uprev CLs for those releases,
and tags the appropriate reviewers. Think of it as the CrOS autoroller.

See go/pupr and go/pupr-generator for rationale and design decisions.
"""

from google.protobuf import json_format

import collections
import itertools
import urlparse

from PB.chromiumos.common import PackageInfo
from PB.chromiumos.common import BuildTarget
from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.recipes.chromeos.generator import ABANDON
from PB.recipes.chromeos.generator import DO_NOTHING
from PB.recipes.chromeos.generator import DRY_RUN
from PB.recipes.chromeos.generator import FULL_RUN
from PB.recipes.chromeos.generator import OutdatedClsPolicy
from PB.recipes.chromeos.generator import OUTDATED_DO_NOTHING
from PB.recipes.chromeos.generator import OUTDATED_LEAVE_COMMENT
from PB.recipes.chromeos.generator import OUTDATED_ABANDON
from PB.recipes.chromeos.generator import GeneratorProperties
from PB.recipes.chromeos.generator import Reviewer
from PB.recipes.chromeos.generator import SendToCqPolicy
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (triggers as
                                                                triggers_pb2)

from google.protobuf import json_format

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'cros_build_api',
    'cros_cq_depends',
    'depot_tools/gitiles',
    'gerrit',
    'cros_sdk',
    'cros_source',
    'git',
    'git_cl',
    'naming',
    'repo',
]

PROPERTIES = GeneratorProperties


def RunSteps(api, properties):
  with api.step.nest('validate properties') as step:
    if not properties.HasField('package_info'):
      raise ValueError('must set package_info')

    if not properties.reviewers:
      raise ValueError('need at least one reviewer')

    for reviewer in properties.reviewers:
      if not reviewer.email:
        raise ValueError('must set reviewer email')

    step.presentation.step_text = 'all properties good'

  package = properties.package_info
  cpv = api.naming.get_package_title(package)

  triggers = properties.triggers or api.scheduler.triggers
  with api.step.nest('validate triggers') as step:
    if not triggers:
      raise ValueError('found no scheduler triggers')

    for trigger in triggers:
      if not trigger.HasField('gitiles'):
        raise ValueError('found non-gitiles trigger: %r', trigger)

    step.presentation.step_text = 'found {} good triggers'.format(len(triggers))
    step.presentation.logs['list of triggers'] = map(json_format.MessageToJson,
                                                     triggers)

  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache()
    if properties.init_sdk:
      with api.context(cwd=api.cros_source.workspace_path), \
           api.step.nest('init sdk') as step:
        response = api.cros_build_api.SdkService.Create(
            CreateSdkRequest(
                flags=CreateSdkRequest.Flags(no_replace=True,
                                             no_use_image=True),
                chroot=api.cros_sdk.chroot))
        step.presentation.logs['sdk version'] = [
            str(response.version.version)
        ]
        # TODO(crbug.com/949721): Currently, chromite depends on the chroot
        # living within the source tree. As a workaround, link the external
        # chroot the workspace to make it look legit. New chromite services
        # should accept the chroot path as a parameter.
        api.cros_sdk.link_chroot(api.cros_source.workspace_path)

    with api.step.nest('try uprev {}'.format(cpv)) as step:
      request = UprevVersionedPackageRequest(
          chroot=api.cros_sdk.chroot,
          package_info=package,
          versions=[
              UprevVersionedPackageRequest.GitRef(
                  repository=urlparse.urlparse(trigger.gitiles.repo).path,
                  ref=trigger.gitiles.ref, revision=trigger.gitiles.revision)
              for trigger in triggers
          ],
          build_targets=properties.build_targets,
      )
      response = api.cros_build_api.PackageService.UprevVersionedPackage(
          request, name='uprev versioned package')
      modified_ebuilds = []
      versions = []
      for uprev_response in response.responses:
        if uprev_response.version:
          versions.append(uprev_response.version)
        for modified_ebuild in uprev_response.modified_ebuilds:
          modified_ebuilds.append(modified_ebuild)

      if not modified_ebuilds or not versions:
        step.presentation.step_text = 'no new versions for {}'.format(cpv)
        return

      valid_responses = []
      with api.step.nest('verify updates'):
        # only act on files that are actually modified
        for uprev_response in response.responses:
          if response_has_changes(api, uprev_response):
            valid_responses.append(uprev_response)

      if not valid_responses:
        step.presentation.step_text = (
            'skipping uprev for {}. no modified files'.format(cpv))
        return

      step.presentation.logs['uprev versions'] = [
          response.version for response in valid_responses
      ]

    topic = properties.topic or cpv

    repositories = []
    with api.step.nest('commit uprev'):
      for uprev_response in valid_responses:
        commit_lines = [
            '{}: Automatic uprev to {}.'.format(package.package_name,
                                                uprev_response.version),
            'Generated by PUpr, see {} for job details.'.format(
                api.buildbucket.build_url()),
            'BUG=None',
            'TEST=CQ',
            # Begin footers after blank line.
            '',
            'Cq-Cl-Tag: pupr:{}'.format(topic),
        ]
        commit_message = '\n\n'.join(commit_lines)

        ebuilds_by_repository = collections.defaultdict(list)
        for ebuild in uprev_response.modified_ebuilds:
          path = ebuild.path
          with api.context(cwd=api.path.abs_to_path(api.path.dirname(path))):
            ebuilds_by_repository[api.git.repository_root()].append(path)

        # Checkout git branches via repo so they track correctly.
        with api.context(cwd=api.cros_source.workspace_path):
          projects = api.repo.project_infos(
              projects=ebuilds_by_repository.keys())
          api.repo.start('pupr',
                         projects=[project.name for project in projects])

        for repository, ebuilds in ebuilds_by_repository.iteritems():
          name = api.path.basename(repository)
          root = api.path.abs_to_path(repository)
          with api.step.nest(
              'commit in {}'.format(name)), api.context(cwd=root):
            api.git.add(ebuilds)
            api.git.commit(commit_message)

        repositories.extend(ebuilds_by_repository.keys())

    with api.step.nest('find open uprev CLs') as step:
      open_changes = []
      for host in ('chromium', 'chrome-internal'):
        with api.step.nest('find CLs from {} host'.format(host)):
          host_url = 'https://{}-review.googlesource.com'.format(host)
          open_changes.extend(
              api.gerrit.query_changes(host_url, [('topic', topic),
                                                  ('status', 'open')]))

    with api.step.nest('generate CLs') as step:
      repositories = map(api.path.abs_to_path, repositories)
      changes = [
          api.gerrit.create_change(
              repository,
              reviewers=[reviewer.email for reviewer in properties.reviewers],
              topic=topic,
          )
          for repository in repositories
      ]

    if len(changes) > 1:
      with api.step.nest('cq-depend generated CLs'):
        cq_depends = api.cros_cq_depends.get_mutual_cq_depend(changes)
        for change, cq_depend in zip(changes, cq_depends):
          with api.step.nest('set cq-depend for {} CL'.format(repository)):
            description = api.gerrit.get_change_description(change).stdout
            description = '{}\n{}'.format(description, cq_depend)
            api.gerrit.set_change_description(change, description)

    existing_cls_policy = properties.existing_cls_policy or DO_NOTHING
    no_existing_cls_policy = properties.no_existing_cls_policy or DO_NOTHING
    outdated_cls_policy = properties.outdated_cls_policy or OUTDATED_DO_NOTHING
    outdated_cls_policy_str = OutdatedClsPolicy.Name(outdated_cls_policy)

    send_to_cq_policy = (
        existing_cls_policy if open_changes else no_existing_cls_policy)

    with api.step.nest('update CL labels'):
      for change in changes:
        # First post explanatory message.
        message_lines = [
            'Found {} open CL(s) for Gerrit topic {}:'.format(
                len(open_changes), topic), '\n'.join(
                    map(api.gerrit.parse_gerrit_change_url, open_changes)),
            'Send-to-cq policy for this case is {}.'.format(
                SendToCqPolicy.Name(send_to_cq_policy))
        ]

        message_lines.append({
            DRY_RUN: 'Therefore, marking CL as CQ+1',
            FULL_RUN: 'Therefore, marking CL as CQ+2',
            ABANDON: 'Therefore, abandoning the CL',
        }.get(
            send_to_cq_policy,
            'Therefore, will NOT mark CL as CQ+1/CQ+2. Reviewers must do so. '
            'Reviewers may also want to abandon the open CL(s).',
        ))

        message = '\n'.join(message_lines)
        if send_to_cq_policy == ABANDON:
          api.gerrit.abandon_change(change, message=message)
        else:
          api.gerrit.add_change_comment(change, message)

        # Then set labels.
        labels = {
            DRY_RUN: {
                api.gerrit.Label.BOT_COMMIT: 1,
                api.gerrit.Label.COMMIT_QUEUE: 1,
            },
            FULL_RUN: {
                api.gerrit.Label.BOT_COMMIT: 1,
                api.gerrit.Label.COMMIT_QUEUE: 2,
            },
        }.get(send_to_cq_policy)

        if labels is not None:
          api.gerrit.set_change_labels(change, labels)

    mrm = None  # Most recently merged uprev.
    if open_changes:
      with api.step.nest('examine outdated CLs'):
        for host in ('chromium', 'chrome-internal'):
          with api.step.nest('merged CLs from {} host (within 30 days)'
              .format(host)) as step:
            host_url = 'https://{}-review.googlesource.com'.format(host)
            merged_changes = api.gerrit.query_changes(
                host_url, [('topic', topic), ('status', 'merged'),
                          ('-age', '30d')])
            if merged_changes:
              step.presentation.logs['merged CLs'] = [
                  api.gerrit.parse_gerrit_change_url(cl)
                  for cl in merged_changes]

              # Must fetch to get submitted times from the "PatchSets", which
              # are really instances of ChangeInfo.
              merged_ci = api.gerrit.fetch_patch_sets(merged_changes)
              list.sort(merged_ci,
                        key=lambda ci: ci.submitted,
                        reverse=True)
              mrm = merged_ci[0] if merged_ci else None
              step.presentation.logs['most recent merged cl'] = [mrm.display_id]

    outdated_cls = []
    if mrm:
      open_ci = api.gerrit.fetch_patch_sets(open_changes)
      with api.step.nest('outdated CLs') as step:
        outdated_cls.extend([ci for ci in open_ci
                             if ci.created < mrm.submitted])
        step.presentation.logs['outdated CLs'] = [
            ci.display_id
            for ci in outdated_cls]

    if outdated_cls:
      with api.step.nest('act on outdated CLs with policy: {}'.format(
                             outdated_cls_policy_str)) as step:
        for outdated_cl in outdated_cls:
          if outdated_cls_policy == OUTDATED_LEAVE_COMMENT:
            outdated_comment_message = ('This CL has been obviated by: {}\n\n'
                                       'PUpr has been set to remind you that it'
                                       ' likely should be abandoned.').format(
                                           mrm.display_url)
            api.gerrit.add_change_comment(outdated_cl.to_gerrit_change_proto(),
                                          outdated_comment_message)
          if outdated_cls_policy == OUTDATED_ABANDON:
            outdated_comment_message = ('This CL has been obviated by: {}\n\n'
                                       'PUpr has been set to abandon.').format(
                                           mrm.display_url)
            api.gerrit.abandon_change(outdated_cl.to_gerrit_change_proto(),
                                      message=outdated_comment_message)


def response_has_changes(api, response):
  """Returns whether the given `UprevPackagesResponse` contains changes."""
  for ebuild in response.modified_ebuilds:
    path = ebuild.path
    with api.context(cwd=api.path.abs_to_path(api.path.dirname(path))):
      if api.git.diff_check(path):
        return True
  return False


def GenTests(api):
  package = PackageInfo(category='chromeos-base', package_name='chromite')
  properties = json_format.MessageToDict(
      GeneratorProperties(
          package_info=package,
          reviewers=[
              Reviewer(email='evanhernandez@chromium.org'),
              Reviewer(email='chromeos-continuous-integration-team@google.com'),
          ],
          build_targets=[
            BuildTarget(name='build_target'),
          ],
      ),)
  gitiles_triggers = [
      triggers_pb2.Trigger(
          id='123',
          gitiles=triggers_pb2.GitilesTrigger(
              repo='chromiumos/chromite',
              ref='refs/heads/master',
              revision='deadbeef',
          ),
      ),
  ]

  yield (api.test('with-uprev-do-nothing-policy') + api.properties(
      existing_cls_policy=DO_NOTHING, **properties) +
         api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True))

  yield (api.test('with-uprev-do-nothing-policy-init-sdk') + api.properties(
      existing_cls_policy=DO_NOTHING, init_sdk=True, **properties) +
         api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True))

  yield (api.test('with-uprev-dry-run-policy') + api.properties(
      existing_cls_policy=DRY_RUN, **properties) +
         api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True))

  yield (api.test('with-uprev-full-run-policy') + api.properties(
      existing_cls_policy=FULL_RUN, **properties) +
         api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True))

  yield (api.test('with-uprev-abandon-policy') + api.properties(
      existing_cls_policy=ABANDON, **properties) +
         api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True))

  yield (api.test('with-uprev-abandon-outdated-policy') + api.properties(
      outdated_cls_policy=OUTDATED_ABANDON, **properties) +
         api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True))

  yield (api.test('with-uprev-abandon-no-nothing-policy') + api.properties(
      outdated_cls_policy=OUTDATED_DO_NOTHING, **properties) +
         api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True))

  yield (api.test('with-uprev-comment-outdated-policy') + api.properties(
      outdated_cls_policy=OUTDATED_LEAVE_COMMENT, **properties) +
         api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True))

  yield api.test('no-package-info') + api.expect_exception('ValueError')

  yield (api.test('no-reviewers') + api.properties(package_info=package) +
         api.expect_exception('ValueError') + api.git.diff_check(True))

  yield (api.test('blank-reviewer') + api.properties(
      package_info=package, reviewers=[{}]) + api.expect_exception('ValueError')
         + api.git.diff_check(True))

  yield (api.test('no-triggers') + api.properties(**properties) +
         api.scheduler(triggers=[]) + api.expect_exception('ValueError') +
         api.git.diff_check(True))

  yield (api.test('non-gitiles-triggers') + api.properties(**properties) +
         api.scheduler(triggers=[
             triggers_pb2.Trigger(id='456', webui=triggers_pb2.WebUITrigger()),
         ]) + api.expect_exception('ValueError') + api.git.diff_check(True))

  yield (api.test('without-uprev') + api.properties(**properties) +
         api.scheduler(triggers=gitiles_triggers) + api.step_data(
             'try uprev chromeos-base/chromite.uprev versioned package'
             '.read output file', api.file.read_raw(content='{}')))

  yield (api.test('no-changes') + api.properties(**properties) +
         api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(False))

  # Set up for testing chromeos-base/chromeos-chrome trigger filtering.
  package = PackageInfo(category='chromeos-base',
                        package_name='chromeos-chrome')
  properties = json_format.MessageToDict(
      GeneratorProperties(
          package_info=package,
          reviewers=[
              Reviewer(email='dburger@chromium.org'),
          ],
          build_targets=[
            BuildTarget(name='build_target'),
          ],
      ),)
  gitiles_triggers = [
      triggers_pb2.Trigger(
          id='123',
          gitiles=triggers_pb2.GitilesTrigger(
              repo='https://chromium.googlesource.com/chromium/src',
              ref='refs/tags/79.0.3945.20',
              revision='83a1812dddfc24f604d92bf61ad58efe9227a6fc',
          ),
      ),
      triggers_pb2.Trigger(
          id='456',
          gitiles=triggers_pb2.GitilesTrigger(
              repo='https://chromium.googlesource.com/chromium/src',
              ref='refs/tags/78.0.3904.88',
              revision='90f293ef4ac440371bc6ff57933eac24cc9de0e4',
          ),
      ),
  ]

  MATCHES_DEPS="""
# Some leading stuff
vars = {
  "buildspec_platforms": "android, chromeos",
  # some comments
  'build_with_chromium': True,
}
"""

  # DEPS with no match.
  NO_MATCHES_DEPS="""
# Some leading stuff
vars = {
  "buildspec_platforms": "win64",
  # some comments
  'build_with_chromium': True,
}
"""

  # Testing direct invocation, that is, not invoked with properties from
  # a gitiles poller through api.scheduler.
  yield (api.test('invoked-directly') +
         api.properties(**properties) +
         api.properties(triggers=[json_format.MessageToDict(t)
                                  for t in gitiles_triggers]))
