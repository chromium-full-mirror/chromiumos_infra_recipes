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

from google.protobuf.json_format import MessageToDict, MessageToJson

from collections import defaultdict, namedtuple
import re
import urlparse

from PB.chromiumos.common import PackageInfo
from PB.chromiumos.common import BuildTarget
from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.recipes.chromeos.generator import (
    SendToCqPolicy,
    DO_NOTHING,
    DRY_RUN,
    FULL_RUN,
    ABANDON,
    OutdatedClsPolicy,
    OUTDATED_DO_NOTHING,
    OUTDATED_LEAVE_COMMENT,
    OUTDATED_ABANDON,
    BranchPolicy,
    Reviewer,
    GeneratorProperties,
)
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import (
    GitilesTrigger, Trigger, WebUITrigger)
from recipe_engine.recipe_api import StepFailure
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'cros_build_api',
    'cros_cq_depends',
    'cros_sdk',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'naming',
    'repo',
    'src_state',
]

PROPERTIES = GeneratorProperties


def RunSteps(api, properties):
  workspace_path = api.cros_source.workspace_path

  global_policy = BranchPolicy(
      pattern='.*',
      repl='',
      reviewers=properties.reviewers,
      topic=properties.topic,
      no_existing_cls_policy=properties.no_existing_cls_policy or DO_NOTHING,
      existing_cls_policy=properties.existing_cls_policy or DO_NOTHING,
      outdated_cls_policy=properties.outdated_cls_policy or OUTDATED_DO_NOTHING,
  )
  policies = list(properties.branch_policies) + [global_policy]

  with api.step.nest('validate properties') as presentation:
    if not properties.HasField('package_info'):
      raise StepFailure('must set package_info')

    for policy in policies:
      if not policy.pattern:
        raise StepFailure('must specify pattern')
      if not policy.reviewers:
        raise StepFailure('need at least one reviewer')

      for reviewer in policy.reviewers:
        if not reviewer.email:
          raise StepFailure('must set reviewer email')

    presentation.step_text = 'all properties good'

  triggers = properties.triggers or api.scheduler.triggers
  with api.step.nest('validate triggers') as presentation:
    if not triggers:
      raise StepFailure('found no scheduler triggers')

    for trigger in triggers:
      if not trigger.HasField('gitiles'):
        raise StepFailure('found non-gitiles trigger: %r', trigger)

    presentation.step_text = 'found {} good triggers'.format(len(triggers))
    presentation.logs['list of triggers'] = map(MessageToJson, triggers)

  package = properties.package_info
  cpv = api.naming.get_package_title(package)

  with api.cros_source.checkout_overlays_context(), \
    api.cros_sdk.cleanup_context(checkout_path=workspace_path):
    api.cros_source.ensure_synced_cache()

    # Check out the appropriate branch, and use the appropriate policy.
    policy = global_policy
    branch = 'master'
    with api.step.nest('determine branch') as pres:
      # TODO(b/167619469): handle the case where we get multiple triggers.
      # For Chrome, we are launched with properties.triggers, for exactly one
      # version.  See http://shortn/_qWgYUlVY6X in trigger_official_builds().
      if len(triggers) > 1:
        raise StepFailure('too many triggers')
      policy_info = _get_policy(api, triggers[0], policies)
      policy = policy_info.policy
      if policy_info.branch:
        branch = policy_info.branch
        pres.step_text = 'using {} {}'.format(policy_info.branch,
                                              policy_info.reference.hash)
        api.cros_source.checkout_branch(api.src_state.internal_manifest.url,
                                        policy_info.branch)
      else:
        pres.step_text = 'using default branch'
    api.easy.set_properties_step(policy=MessageToDict(policy))

    if properties.init_sdk:
      with api.context(cwd=workspace_path):
        api.cros_sdk.create_chroot(use_image=False)

    with api.step.nest('try uprev {}'.format(cpv)) as presentation:
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

      if not response.responses:
        presentation.step_text = 'no new versions for {}'.format(cpv)
        return

      valid_responses = []
      with api.step.nest('verify updates'):
        # only act on files that are actually modified
        for uprev_resp in response.responses:
          if response_has_changes(api, uprev_resp):
            valid_responses.append(uprev_resp)

      if not valid_responses:
        presentation.step_text = (
            'skipping uprev for {}. no modified files'.format(cpv))
        return

      presentation.logs['uprev versions'] = [
          response.version for response in valid_responses
      ]

    Ebuilds = namedtuple('Ebuilds', 'path version')

    topic = policy.topic or cpv
    existing_cls_policy = policy.existing_cls_policy
    no_existing_cls_policy = policy.no_existing_cls_policy
    outdated_cls_policy = policy.outdated_cls_policy

    with api.step.nest('commit uprev'):
      # Collect the changes by repository, so can do one CL per repository.
      ebuilds_by_repo = defaultdict(list)
      for uprev_resp in valid_responses:
        for ebuild in uprev_resp.modified_ebuilds:
          path = ebuild.path
          with api.context(cwd=api.path.abs_to_path(api.path.dirname(path))):
            ebuilds_by_repo[api.git.repository_root()].append(
                Ebuilds(path=path, version=uprev_resp.version))

      # Checkout git branches via repo so they track correctly.
      with api.context(cwd=workspace_path):
        projects = api.repo.project_infos(projects=ebuilds_by_repo.keys())
        api.repo.start('pupr', projects=[project.name for project in projects])

      # For each repository, make the CL.
      for repository, ebuilds in ebuilds_by_repo.iteritems():
        name = api.path.basename(repository)
        root = api.path.abs_to_path(repository)
        versions = ', '.join(sorted(set([e.version for e in ebuilds])))
        commit_lines = [
            '{}: Automatic uprev to {}.'.format(package.package_name, versions),
            'Generated by PUpr, see {} for job details.'.format(
                api.buildbucket.build_url()),
            'BUG=None',
            'TEST=CQ',
            # Begin footers after blank line.
            '',
            'Cq-Cl-Tag: pupr:{}'.format(topic),
        ]
        commit_message = '\n\n'.join(commit_lines)

        with api.step.nest('commit in {}'.format(name)), api.context(cwd=root):
          api.git.add([e.path for e in ebuilds])
          api.git.commit(commit_message)

    with api.step.nest('find open uprev CLs'):
      open_changes = []
      for host in ('chromium', 'chrome-internal'):
        with api.step.nest('find CLs from {} host'.format(host)):
          host_url = 'https://{}-review.googlesource.com'.format(host)
          open_changes.extend(
              api.gerrit.query_changes(host_url, [('topic', topic),
                                                  ('branch', branch),
                                                  ('status', 'open')]))

    mrm = None  # Most recently merged uprev.
    if open_changes:
      with api.step.nest('examine outdated CLs'):
        for host in ('chromium', 'chrome-internal'):
          with api.step.nest('merged CLs from {} host (within 30 days)'.format(
              host)) as presentation:
            host_url = 'https://{}-review.googlesource.com'.format(host)
            merged_changes = api.gerrit.query_changes(host_url,
                                                      [('topic', topic),
                                                       ('branch', branch),
                                                       ('status', 'merged'),
                                                       ('-age', '30d')])
            if merged_changes:
              presentation.logs['merged CLs'] = [
                  api.gerrit.parse_gerrit_change_url(cl)
                  for cl in merged_changes
              ]

              # Must fetch to get submitted times from the "PatchSets", which
              # are really instances of ChangeInfo.
              merged_ci = api.gerrit.fetch_patch_sets(merged_changes)
              list.sort(merged_ci, key=lambda ci: ci.submitted, reverse=True)
              mrm = merged_ci[0] if merged_ci else None
              presentation.logs['most recent merged cl'] = [mrm.display_id]

    outdated_cls, abandoned_cls = [], []
    if mrm:
      open_ci = api.gerrit.fetch_patch_sets(open_changes)
      with api.step.nest('outdated CLs') as presentation:
        outdated_cls.extend(
            [ci for ci in open_ci if ci.created < mrm.submitted])
        presentation.logs['outdated CLs'] = [
            ci.display_id for ci in outdated_cls
        ]

    if outdated_cls:
      with api.step.nest('act on outdated CLs with policy: {}'.format(
          OutdatedClsPolicy.Name(outdated_cls_policy))):
        for outdated_cl in outdated_cls:
          if outdated_cls_policy == OUTDATED_LEAVE_COMMENT:
            outdated_comment_message = (
                'This CL has been obviated by: {}\n\n'
                'PUpr has been set to remind you that it'
                ' likely should be abandoned.').format(mrm.display_url)
            api.gerrit.add_change_comment(outdated_cl.to_gerrit_change_proto(),
                                          outdated_comment_message)
          elif outdated_cls_policy == OUTDATED_ABANDON:
            outdated_comment_message = ('This CL has been obviated by: {}\n\n'
                                        'PUpr has been set to abandon.').format(
                                            mrm.display_url)
            api.gerrit.abandon_change(outdated_cl.to_gerrit_change_proto(),
                                      message=outdated_comment_message)
            abandoned_cls.append(outdated_cl)

    with api.step.nest('generate CLs'):
      repositories = map(api.path.abs_to_path, ebuilds_by_repo.keys())
      changes = [
          api.gerrit.create_change(
              repository,
              reviewers=[reviewer.email for reviewer in policy.reviewers],
              topic=topic,
          ) for repository in repositories
      ]

    if changes:
      with api.step.nest('cq-depend generated CLs'):
        cq_depends = api.cros_cq_depends.get_mutual_cq_depend(changes)
        for change, cq_depend in zip(changes, cq_depends):
          with api.step.nest('set cq-depend for {} CL'.format(repository)):
            description = api.gerrit.get_change_description(change)
            description = '{}\n{}'.format(description, cq_depend)
            api.gerrit.set_change_description(change, description)

    existing_cls = open_changes and len(abandoned_cls) < len(open_changes)
    send_to_cq_policy = (
        existing_cls_policy if existing_cls else no_existing_cls_policy)

    with api.step.nest('update CL labels'):
      for change in changes:
        # First post explanatory message.
        message_lines = [
            'Found {} open CL(s) for Gerrit topic {}:'.format(
                len(open_changes), topic),
            '\n'.join(map(api.gerrit.parse_gerrit_change_url, open_changes)),
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


def _get_policy(api, trigger, policies):
  """Find the applicable policy for the trigger.

  The policy used is the first policy where policy.pattern matches the tag, and
  either:
  - the substitution result is the empty string (default branch, aka legacy), or
  - a remote reference is in manifest-internal for the substitution result.

  Returns:
    (PolicyInfo) namedtuple with:
    - policy (BranchPolicy): The selected policy
    - branch (str): the branch to checkout.  Empty if there is no branch to
      checkout.
    - reference (git.Reference): the reference that matched, or None.
  """
  PolicyInfo = namedtuple('PolicyInfo', ['policy', 'branch', 'reference'])
  manifest = api.src_state.internal_manifest
  tag = trigger.gitiles.ref
  with api.context(cwd=manifest.path):
    for policy in policies:
      if re.match(policy.pattern, tag):
        query = re.sub(policy.pattern, policy.repl, tag)
        if not query:
          return PolicyInfo(policy, '', None)
        refs = api.git.ls_remote([query])
        if len(refs) == 1:
          ref = refs[0]
          return PolicyInfo(policy, ref.ref.split('/')[-1], ref)
        elif refs:
          raise StepFailure('multiple branches matched {}: {}'.format(
              query, ' '.join(x.ref for x in refs)))
        # If we found no references, this policy does not apply.

    # TODO(b/167619469): Once the global policy properties are gone this will
    # become reachable, and needs to be tested.  We will know, because we will
    # return None here and not have a valid PolicyInfo.
    # raise StepFailure('No matching policy found for tag {}'.format(tag))


# TODO(dburger): deleted files should be at the end of the modified_ebuilds list
# to work correctly with api.git.diff_check.
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
  properties = MessageToDict(
      GeneratorProperties(
          package_info=package,
          reviewers=[
              Reviewer(email='evanhernandez@chromium.org'),
              Reviewer(email='chromeos-continuous-integration-team@google.com'),
          ],
          build_targets=[
              BuildTarget(name='build_target'),
          ],
      ),
  )
  gitiles_triggers = [
      Trigger(
          id='123',
          gitiles=GitilesTrigger(
              repo='chromiumos/chromite',
              ref='refs/heads/master',
              revision='deadbeef',
          ),
      ),
  ]

  yield api.test(
      'with-uprev-do-nothing-policy',
      api.properties(existing_cls_policy=DO_NOTHING, **properties),
      api.scheduler(triggers=gitiles_triggers),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-do-nothing-policy-init-sdk',
      api.properties(existing_cls_policy=DO_NOTHING, init_sdk=True,
                     **properties),
      api.scheduler(triggers=gitiles_triggers),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-dry-run-policy',
      api.properties(existing_cls_policy=DRY_RUN, **properties),
      api.scheduler(triggers=gitiles_triggers),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-full-run-policy',
      api.properties(existing_cls_policy=FULL_RUN, **properties),
      api.scheduler(triggers=gitiles_triggers),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-abandon-policy',
      api.properties(existing_cls_policy=ABANDON, **properties),
      api.scheduler(triggers=gitiles_triggers),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-abandon-outdated-policy',
      api.properties(outdated_cls_policy=OUTDATED_ABANDON, **properties),
      api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-abandon-no-nothing-policy',
      api.properties(outdated_cls_policy=OUTDATED_DO_NOTHING, **properties),
      api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-comment-outdated-policy',
      api.properties(outdated_cls_policy=OUTDATED_LEAVE_COMMENT, **properties),
      api.scheduler(triggers=gitiles_triggers) + api.git.diff_check(True),
  )

  yield api.test(
      'no-package-info',
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'no-reviewers',
      api.properties(package_info=package),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'blank-reviewer',
      api.properties(package_info=package, reviewers=[{}]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'no-triggers',
      api.properties(**properties),
      api.scheduler(triggers=[]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'non-gitiles-triggers',
      api.properties(**properties),
      api.scheduler(triggers=[
          Trigger(id='456', webui=WebUITrigger()),
      ]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'without-uprev',
      api.properties(**properties),
      api.scheduler(triggers=gitiles_triggers),
      api.step_data(
          'try uprev chromeos-base/chromite.uprev versioned package'
          '.read output file', api.file.read_raw(content='{}')),
  )

  yield api.test(
      'no-changes',
      api.properties(**properties),
      api.scheduler(triggers=gitiles_triggers),
      api.git.diff_check(False),
  )

  # Set up for testing chromeos-base/chromeos-chrome trigger filtering.
  package = PackageInfo(category='chromeos-base',
                        package_name='chromeos-chrome')
  properties = MessageToDict(
      GeneratorProperties(
          package_info=package,
          reviewers=[
              Reviewer(email='dburger@chromium.org'),
          ],
          build_targets=[
              BuildTarget(name='build_target'),
          ],
      ),
  )
  gitiles_triggers = [
      Trigger(
          id='123',
          gitiles=GitilesTrigger(
              repo='https://chromium.googlesource.com/chromium/src',
              ref='refs/tags/79.0.3945.20',
              revision='83a1812dddfc24f604d92bf61ad58efe9227a6fc',
          ),
      ),
  ]

  # Testing direct invocation, that is, not invoked with properties from
  # a gitiles poller through api.scheduler.
  yield api.test(
      'invoked-directly',
      api.properties(**properties),
      api.properties(triggers=[MessageToDict(t) for t in gitiles_triggers]),
  )

  branch_policy = BranchPolicy(
      pattern='refs/tags/([0-9]*).*',
      repl=r'release-R\1-*.B',
      reviewers=[Reviewer(email='dburger@chromium.org')],
      no_existing_cls_policy=DRY_RUN,
      existing_cls_policy=DRY_RUN,
      outdated_cls_policy=OUTDATED_ABANDON,
  )
  no_pattern_policy = BranchPolicy(
      pattern='',
      repl=r'release-R\1-*.B',
      reviewers=[Reviewer(email='dburger@chromium.org')],
      no_existing_cls_policy=DRY_RUN,
      existing_cls_policy=DRY_RUN,
      outdated_cls_policy=OUTDATED_ABANDON,
  )

  yield api.test(
      'branch-policies',
      api.properties(**properties),
      api.properties(triggers=[MessageToDict(t) for t in gitiles_triggers]),
      api.properties(branch_policies=[MessageToDict(branch_policy)]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.MustRun,
                     'determine branch.checkout branch release-R79-*.B'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'branch-policies-multiple-triggers',
      api.properties(**properties),
      api.properties(triggers=[MessageToDict(t) for t in gitiles_triggers * 2]),
      api.properties(branch_policies=[MessageToDict(branch_policy)]),
      api.post_check(post_process.DoesNotRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'branch-policies-no-pattern',
      api.properties(**properties),
      api.properties(triggers=[MessageToDict(t) for t in gitiles_triggers * 2]),
      api.properties(branch_policies=[MessageToDict(no_pattern_policy)]),
      api.post_check(post_process.DoesNotRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'branch-policies-default-branch',
      api.properties(**properties),
      api.properties(triggers=[MessageToDict(t) for t in gitiles_triggers]),
      api.properties(branch_policies=[
          MessageToDict(
              BranchPolicy(pattern='.*', repl='',
                           reviewers=[Reviewer(email='a@example.com')]))
      ]),
      api.post_check(post_process.DoesNotRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'branch-policies-multi-ref',
      api.properties(**properties),
      api.properties(triggers=[MessageToDict(t) for t in gitiles_triggers]),
      api.properties(branch_policies=[MessageToDict(branch_policy)]),
      api.step_data(
          'determine branch.git ls-remote',
          stdout=api.raw_io.output_text('\n'.join([
              '9ed37bc6f515ef0ef42949d9f23e1180432649f5\t'
              'refs/remotes/cros-internal/release-R79-5555.B',
              'f3ecd792bc4822dd6686313478099b8eb3df7e55\t'
              'refs/remotes/cros-internal/release-R79-9999.B',
          ]) + '\n')),
      api.post_check(post_process.StatusAnyFailure),
  )
