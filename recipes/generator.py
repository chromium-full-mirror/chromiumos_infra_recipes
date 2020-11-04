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
    RetryClPolicy,
    NO_RETRY,
    RETRY_LATEST_OR_LATEST_PINNED,
    RETRY_LATEST_PINNED,
    BranchPolicy,
    Reviewer,
    GeneratorProperties,
)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1.triggers import (
    GitilesTrigger, Trigger, WebUITrigger)
from recipe_engine.recipe_api import StepFailure
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
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

HASHTAG_FREEZE_RETRIES = "pupr-freeze-retries"
HASHTAG_PINNED_RETRY = "pupr-retry-pinned"

# TODO(jackneus): After generator has run for real on the chrome package, look at the
# gerrit-fetch-changes step output to get a better idea of the 'CQ is trying...' message
# and change the simple "in" queries below to narrower and more precise regexp matching.


# Determine if the CL in question is in a failed state.
def is_failed_cl(c):
  # c.messages is sorted in ascending order of date. Reverse to get most recent first.
  for m in reversed(c.messages):
    if "Failed builds" in m["message"]:
      return True
  return False


# Determine if the CL in question is in a running state.
def is_running_cl(c):
  # c.messages is sorted in ascending order of date. Reverse to get most recent first.
  for m in reversed(c.messages):
    # If we hit a try message before a failed message, the change
    # hasn't failed yet for the most recent run.
    if "CQ is trying the patch" in m["message"]:
      return True
    if "Failed builds" in m["message"]:
      break
  return False


def RunSteps(api, properties):
  workspace_path = api.cros_source.workspace_path

  policies = list(properties.branch_policies)

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
    branch = 'master'
    with api.step.nest('determine branch') as pres:
      trigger_policies = []
      for trigger in triggers:
        policy_info = _get_policy(api, trigger, policies)
        if policy_info not in trigger_policies:
          trigger_policies.append(policy_info)
      # If we match more than one policy with the triggers, that is an error.
      # For Chrome, we are launched with properties.triggers, for exactly one
      # version.  See http://shortn/_qWgYUlVY6X in trigger_official_builds().
      if len(trigger_policies) > 1:
        raise StepFailure('too many triggers')
      policy_info = trigger_policies.pop()
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
    retry_cl_policy = policy.retry_cl_policy or NO_RETRY

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
          OutdatedClsPolicy.Name(outdated_cls_policy))) as pres:
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
            try:
              api.gerrit.abandon_change(outdated_cl.to_gerrit_change_proto(),
                                        message=outdated_comment_message)
              abandoned_cls.append(outdated_cl)
            except api.step.StepFailure as ex:  # pragma: no cover
              pres.step_text = 'CL abandon failed: {}'.format(
                  ex.reason_message())

    existing_cls = open_changes and len(abandoned_cls) < len(open_changes)
    send_to_cq_policy = (
        existing_cls_policy if existing_cls else no_existing_cls_policy)

    if retry_cl_policy != NO_RETRY and existing_cls_policy != FULL_RUN:
      with api.step.nest('apply retry policy {}'.format(
          RetryClPolicy.Name(retry_cl_policy))) as presentation:
        if open_changes:
          open_ci = api.gerrit.fetch_patch_sets(open_changes,
                                                include_messages=True)

          # Check for freeze hashtag
          # TODO(jackneus|engeg): Check all open CLs, or only those that are not outdated?
          freeze_retries = any(
              [HASHTAG_FREEZE_RETRIES in ci.hashtags for c in open_ci])

          # Filter out outdated CLs, sort by recency
          open_ci = sorted([ci for ci in open_ci if ci.created > mrm.submitted],
                           key=lambda ci: ci.created, reverse=True)

          # If an open CL had the hashtag HASHTAG_FREEZE_RETRIES, do not attempt retry
          # regardless of policy. Similarly, if send_to_cq_policy is FULL_RUN the new
          # CL will be itself submitted to the CQ, so a retry is not useful.
          if not freeze_retries and send_to_cq_policy != FULL_RUN:
            # Look for open cl with hashtag HASHTAG_PINNED_RETRY
            retry_ci = None
            for ci in open_ci:
              if HASHTAG_PINNED_RETRY in ci.hashtags:
                retry_ci = ci
                break

            # If we haven't identified a pinned CL and the retry policy is not RETRY_PINNED_ONLY,
            # find most recent failed CL.
            if retry_cl_policy != RETRY_LATEST_PINNED and not retry_ci:
              # Filter out CLs that haven't failed (i.e. been tried at least once)
              failed_ci = list(filter(is_failed_cl, open_ci))

              if failed_ci:
                # Sort to get most recent failed
                list.sort(failed_ci, key=lambda ci: ci.created, reverse=True)
                retry_ci = failed_ci[0]

            if retry_ci and is_failed_cl(
                retry_ci) and not is_running_cl(retry_ci):
              with api.step.nest("retry CL {}".format(retry_ci.change_id)):
                # Then set labels.
                labels = {
                    api.gerrit.Label.BOT_COMMIT: 1,
                    api.gerrit.Label.COMMIT_QUEUE: 2,
                }
                api.gerrit.set_change_labels(retry_ci.to_gerrit_change_proto(),
                                             labels)

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

  def _policy(**kwargs):
    """Create a BranchPolicy, with defaults."""
    kwargs.setdefault('pattern', '.*')
    kwargs.setdefault('reviewers', [
        Reviewer(email='evanhernandez@chromium.org'),
        Reviewer(email='chromeos-continuous-integration-team@google.com')
    ])
    kwargs.setdefault('existing_cls_policy', DO_NOTHING)
    kwargs.setdefault('no_existing_cls_policy', DO_NOTHING)
    kwargs.setdefault('outdated_cls_policy', OUTDATED_DO_NOTHING)
    kwargs.setdefault('retry_cl_policy', NO_RETRY)
    return BranchPolicy(**kwargs)

  def _props(**kwargs):
    """Create GeneratorProperties, with defaults."""
    kwargs.setdefault(
        'package_info',
        PackageInfo(category='chromeos-base', package_name='chromite'))
    kwargs.setdefault('build_targets', [BuildTarget(name='build_target')])
    kwargs.setdefault('branch_policies', [_policy()])
    return api.properties(GeneratorProperties(**kwargs))

  chromite_gitiles_trigger = Trigger(
      id='123',
      gitiles=GitilesTrigger(
          repo='chromiumos/chromite',
          ref='refs/heads/master',
          revision='deadbeef',
      ),
  )

  yield api.test(
      'with-uprev-do-nothing-policy',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-do-nothing-policy-init-sdk',
      _props(init_sdk=True),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-dry-run-policy',
      _props(branch_policies=[_policy(existing_cls_policy=DRY_RUN)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-full-run-policy',
      _props(branch_policies=[_policy(existing_cls_policy=FULL_RUN)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-abandon-policy',
      _props(branch_policies=[_policy(existing_cls_policy=ABANDON)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-abandon-outdated-policy',
      _props(branch_policies=[_policy(outdated_cls_policy=OUTDATED_ABANDON)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-abandon-no-nothing-policy',
      _props(branch_policies=[_policy(
          outdated_cls_policy=OUTDATED_DO_NOTHING)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'with-uprev-comment-outdated-policy',
      _props(
          branch_policies=[_policy(
              outdated_cls_policy=OUTDATED_LEAVE_COMMENT)]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
  )

  yield api.test(
      'no-package-info',
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'no-reviewers',
      _props(branch_policies=[_policy(reviewers=None)]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'blank-reviewer',
      _props(branch_policies=[_policy(reviewers=[{}])]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'no-triggers',
      _props(),
      api.scheduler(triggers=[]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'non-gitiles-triggers',
      _props(),
      api.scheduler(triggers=[
          Trigger(id='456', webui=WebUITrigger()),
      ]),
      api.post_check(post_process.StatusAnyFailure),
      api.git.diff_check(True),
  )

  yield api.test(
      'without-uprev',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.step_data(
          'try uprev chromeos-base/chromite.uprev versioned package'
          '.read output file', api.file.read_raw(content='{}')),
  )

  yield api.test(
      'no-changes',
      _props(),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(False),
  )

  # Set up for testing chromeos-base/chromeos-chrome trigger filtering.
  package_chrome = PackageInfo(category='chromeos-base',
                               package_name='chromeos-chrome')
  trigger_prop = MessageToDict(
      Trigger(
          id='123',
          gitiles=GitilesTrigger(
              repo='https://chromium.googlesource.com/chromium/src',
              ref='refs/tags/79.0.3945.20',
              revision='83a1812dddfc24f604d92bf61ad58efe9227a6fc',
          ),
      ))

  trigger_prop2 = MessageToDict(
      Trigger(
          id='456',
          gitiles=GitilesTrigger(
              repo='https://chromium.googlesource.com/chromium/src',
              ref='refs/heads/master',
              revision='0572e38c2b2073613ee5b861a9165335621bf54a',
          ),
      ))

  # Testing direct invocation, that is, not invoked with properties from
  # a gitiles poller through api.scheduler.
  yield api.test(
      'invoked-directly',
      _props(
          package_info=package_chrome, branch_policies=[
              _policy(reviewers=[Reviewer(email='dburger@chromium.org')])
          ]),
      api.properties(triggers=[trigger_prop]),
  )

  branch_policy = _policy(
      pattern='refs/tags/([0-9]*).*',
      repl=r'release-R\1-*.B',
      reviewers=[Reviewer(email='dburger@chromium.org')],
      no_existing_cls_policy=DRY_RUN,
      existing_cls_policy=DRY_RUN,
      outdated_cls_policy=OUTDATED_ABANDON,
  )
  no_pattern_policy = _policy(
      pattern='',
      repl=r'release-R\1-*.B',
      reviewers=[Reviewer(email='dburger@chromium.org')],
      no_existing_cls_policy=DRY_RUN,
      existing_cls_policy=DRY_RUN,
      outdated_cls_policy=OUTDATED_ABANDON,
  )

  yield api.test(
      'branch-policies',
      api.properties(triggers=[trigger_prop]),
      _props(package_info=package_chrome, branch_policies=[branch_policy]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.MustRun,
                     'determine branch.checkout branch release-R79-*.B'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'branch-policies-multiple-triggers',
      api.properties(triggers=[trigger_prop] * 2),
      _props(package_info=package_chrome, branch_policies=[branch_policy]),
      api.git.diff_check(True),
      api.post_check(post_process.MustRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.MustRun,
                     'determine branch.checkout branch release-R79-*.B'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'branch-policies-multiple-trigger-policies',
      api.properties(triggers=[trigger_prop, trigger_prop2]),
      _props(package_info=package_chrome,
             branch_policies=[branch_policy, _policy()]),
      api.post_check(post_process.MustRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'branch-policies-no-pattern',
      api.properties(triggers=[trigger_prop]),
      _props(package_info=package_chrome, branch_policies=[no_pattern_policy]),
      api.post_check(post_process.DoesNotRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'branch-policies-default-branch',
      api.properties(triggers=[trigger_prop]),
      _props(
          package_info=package_chrome, branch_policies=[
              BranchPolicy(pattern='.*', repl='',
                           reviewers=[Reviewer(email='a@example.com')])
          ]),
      api.post_check(post_process.DoesNotRun, 'determine branch.git ls-remote'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'branch-policies-multi-ref',
      api.properties(triggers=[trigger_prop]),
      _props(package_info=package_chrome, branch_policies=[branch_policy]),
      api.step_data(
          'determine branch.git ls-remote',
          stdout=api.raw_io.output_text('\n'.join([
              '9ed37bc6f515ef0ef42949d9f23e1180432649f5\t'
              'refs/remotes/cros-internal/release-R79-5555.B',
              'f3ecd792bc4822dd6686313478099b8eb3df7e55\t'
              'refs/remotes/cros-internal/release-R79-9999.B',
              '',
          ]))),
      api.post_check(post_process.StatusAnyFailure),
  )

  changes = [
      common_pb2.GerritChange(change=1,
                              host='chromium-review.googlesource.com'),
      common_pb2.GerritChange(change=2,
                              host='chromium-review.googlesource.com'),
  ]

  value_dict = {
      1: {
          "change_id":
              "1",
          "created":
              "2020-10-22 18:54:00.000000000",
          "messages": [{
              "message": "CQ is trying the patch..."
          }, {
              "message": "Failed builds: ..."
          }]
      },
      2: {
          "change_id": 2,
          "created": "2020-10-23 18:54:00.000000000",
      },
  }

  yield api.test(
      'with-retry-policy',
      _props(branch_policies=[
          _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED,
                  existing_cls_policy=DRY_RUN, no_existing_cls_policy=DRY_RUN)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED', changes,
          value_dict),
  )

  changes = [
      common_pb2.GerritChange(change=1,
                              host='chromium-review.googlesource.com'),
  ]

  value_dict = {
      1: {
          "change_id":
              1,
          "created":
              "2020-10-22 18:54:00.000000000",
          "hashtags": [HASHTAG_PINNED_RETRY],
          "messages": [{
              "message": "CQ is trying the patch..."
          }, {
              "message": "Failed builds: ..."
          }, {
              "message": "CQ is trying the patch..."
          }]
      }
  }

  yield api.test(
      'with-retry-pinned-policy-selected-cl-running',
      _props(branch_policies=[
          _policy(retry_cl_policy=RETRY_LATEST_PINNED,
                  existing_cls_policy=DRY_RUN, no_existing_cls_policy=DRY_RUN)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_PINNED', changes, value_dict),
  )

  changes = [
      common_pb2.GerritChange(change=1),
  ]

  value_dict = {1: {"change_id": 1, "hashtags": [HASHTAG_FREEZE_RETRIES]}}

  yield api.test(
      'retry-freeze',
      _props(branch_policies=[
          _policy(retry_cl_policy=RETRY_LATEST_OR_LATEST_PINNED)
      ]),
      api.scheduler(triggers=[chromite_gitiles_trigger]),
      api.git.diff_check(True),
      api.gerrit.set_gerrit_fetch_changes_response(
          'apply retry policy RETRY_LATEST_OR_LATEST_PINNED', changes,
          value_dict),
  )
