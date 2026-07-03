# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for interfacing with Gerrit in PUpr (Parallel Uprevs)."""

from typing import Dict, List, Optional

from google.protobuf.json_format import MessageToDict
from recipe_engine import recipe_api
from recipe_engine.config_types import Path

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos.generator import ABANDON
from PB.recipes.chromeos.generator import BranchPolicy
from PB.recipes.chromeos.generator import CR_REJECT
from PB.recipes.chromeos.generator import DRY_RUN
from PB.recipes.chromeos.generator import DRY_RUN_NOT_APPROVED
from PB.recipes.chromeos.generator import FULL_RUN
from PB.recipes.chromeos.generator import NO_RETRY
from PB.recipes.chromeos.generator import OUTDATED_ABANDON
from PB.recipes.chromeos.generator import OUTDATED_LEAVE_COMMENT
from PB.recipes.chromeos.generator import OutdatedClsPolicy
from PB.recipes.chromeos.generator import RetryClPolicy
from PB.recipes.chromeos.generator import SUBMIT
from PB.recipes.chromeos.generator import SendToCqPolicy
from RECIPE_MODULES.chromeos.gerrit.api import Label
from RECIPE_MODULES.chromeos.gerrit.api import PatchSet
from RECIPE_MODULES.chromeos.repo.api import ProjectInfo

# HOSTS_REMOTES contains tuples (host, remote) representing our Gerrit
# instances, where host the section of the Gerrit URL that would be formatted
# into f'https://{host}-review.googlesource.com', and remote is the name of that
# host's corresponding git remote.
HOSTS_REMOTES = (('chromium', 'cros'), ('chrome-internal', 'cros-internal'))

# ProjectsByRemote maps Git remotes to repo projects relevant to this PUpr.
ProjectsByRemote = Dict[str, List[ProjectInfo]]


class PuprGerritInterfaceApi(recipe_api.RecipeApi):
  """A module to interface between PUpr builders and Gerrit."""

  def __init__(self, *args, **kwargs):
    """Initialize the module's attributes."""
    super().__init__(*args, **kwargs)
    self.rebase_before_retry = False

  @property
  def workspace_path(self) -> Path:
    """Return the checkout path where the build is processed."""
    return self.m.cros_source.workspace_path

  def set_generator_attributes(self, rebase_before_retry: bool):
    """Set attributes whose values are determined in Generator.

    Args:
      rebase_before_retry: Whether to rebase open changes before retrying. See
        documentation in generator.proto.

    TODO(b/259445191): All of these attributes should be moved from
      generator.proto to pupr_local_uprev.proto.
    """
    self.rebase_before_retry = rebase_before_retry

  def sort_projects_by_remote(self,
                              projects: List[ProjectInfo]) -> ProjectsByRemote:
    """Return a dict which sorts the given projects by their remote."""
    projects_by_remote: ProjectsByRemote = {}
    for project in projects:
      remote = project.remote
      if remote not in projects_by_remote:
        projects_by_remote[remote] = []
      projects_by_remote[remote].append(project)
    return projects_by_remote

  def find_open_uprev_cls(self, projects_by_remote: ProjectsByRemote,
                          topic: str) -> List[GerritChange]:
    """Return any open uprev CLs matching the right projects and topic.

    Args:
      projects_by_remote: A mapping from Git remotes to repo projects on that
        remote that are relevant to this PUpr.
      topic: A string to match against CLs' Gerrit topic, which is used to
        identify relevant PUpr CLs.
    """
    open_changes: List[GerritChange] = []
    with self.m.step.nest('find open uprev CLs'):
      for host, remote in HOSTS_REMOTES:
        with self.m.step.nest('find CLs from {} host'.format(host)):
          host_url = 'https://{}-review.googlesource.com'.format(host)
          for project in projects_by_remote.get(remote, []):
            open_changes.extend(
                self.m.gerrit.query_changes(host_url,
                                            [('topic', topic),
                                             ('project', project.name),
                                             ('branch', project.branch_name),
                                             ('status', 'open')]))
    return open_changes

  def handle_outdated_changes(self, open_changes: List[GerritChange],
                              most_recent_uprev: PatchSet, policy: BranchPolicy,
                              retry_only_run: bool) -> bool:
    """Abandon already-open and outdated uprev CLs.

    Args:
      open_changes: A list of currently open, relevant PUpr CLs.
      most_recent_uprev: The most recently merged uprev CL.
      policy: The policy selected by this PUpr run.
      retry_only_run: this weirdly named property only causes a run in
        `OUTDATED_LEAVE_COMMENT` mode to not actually leave a comment if true.

    Returns:
      A bool stating whether any open CLs remain after abandoning.
    """
    outdated_cls = self._get_outdated_cls(open_changes, most_recent_uprev)
    abandoned_cls = self._abandon_outdated_cls(outdated_cls, most_recent_uprev,
                                               policy.outdated_cls_policy,
                                               retry_only_run)
    return len(abandoned_cls) < len(open_changes)

  def handle_repeatedly_failing_changes(
      self, open_changes: List[GerritChange], max_cq_retry: int,
      should_count_dry_run: bool) -> List[GerritChange]:
    """Abandon unpinned uprev CLs that have failed too many times and return the
    remaining open CLs.

    Args:
      open_changes: A list of currently open, relevant PUpr CLs.
      max_cq_retry: The maximum number of times an unpinned uprev CL is allowed
        to fail full CQ before abandoning it. Negative number indicates no CL
        should be abandoned no matter how many times it has failed.
      should_count_dry_run: Boolean flag to indicate whether dry run CQ+1
        should be counted.
    """
    # Do not abandon any CL.
    if max_cq_retry < 0:
      return open_changes

    # Do nothing if there is no open changes (gerrit.fetch_patch_sets will
    # exit with 'no changes requested' error).
    if len(open_changes) == 0:
      return open_changes

    with self.m.step.nest('get CLs repeatedly failing CQ') as presentation:
      open_patch_sets = self.m.gerrit.fetch_patch_sets(
          open_changes,
          include_messages=True,
      )

      failing_patchsets = []
      remaining_open_cls = []
      for i, ps in enumerate(open_patch_sets):
        retry_count = (
            self.m.pupr.num_dry_run_cq_failures(ps)
            if should_count_dry_run else self.m.pupr.num_full_cq_failures(ps))
        if (self.m.pupr.is_cl_pinned(ps) or retry_count <= max_cq_retry):
          remaining_open_cls.append(open_changes[i])
        else:
          failing_patchsets.append(ps)

      presentation.logs['max CQ retry'] = str(max_cq_retry)

    if failing_patchsets:
      with self.m.step.nest('abandon unpinned CLs repeatedly failing CQ'):
        for ps in failing_patchsets:
          comment_message = (
              'This CL is abandoned by PUpr since it has failed CQ > {} times.'
          ).format(max_cq_retry)
          self.m.gerrit.abandon_change(ps.to_gerrit_change_proto(),
                                       message=comment_message)

    return remaining_open_cls

  def find_most_recently_merged_uprev(self,
                                      projects_by_remote: ProjectsByRemote,
                                      topic: str) -> PatchSet:
    """Return the most recently merged relevant uprev.

    Args:
      projects_by_remote: A mapping from Git remotes to repo projects on that
        remote that are relevant to this PUpr.
    """
    most_recent_uprev: Optional[PatchSet] = None
    with self.m.step.nest('examine outdated CLs'):
      for host, remote in HOSTS_REMOTES:
        with self.m.step.nest('merged CLs from {} host (within 30 days)'.format(
            host)) as presentation:
          host_url = 'https://{}-review.googlesource.com'.format(host)
          merged_changes = []
          for project in projects_by_remote.get(remote, []):
            merged_changes.extend(
                self.m.gerrit.query_changes(host_url,
                                            [('topic', topic),
                                             ('project', project.name),
                                             ('branch', project.branch_name),
                                             ('status', 'merged'),
                                             ('-age', '30d')]))
          if merged_changes:
            presentation.logs['merged CLs'] = [
                self.m.gerrit.parse_gerrit_change_url(cl)
                for cl in merged_changes
            ]
            # Must fetch to get submitted times from the "PatchSets", which are
            # really instances of ChangeInfo.
            merged_change_infos = self.m.gerrit.fetch_patch_sets(merged_changes)
            merged_change_infos.sort(key=lambda ci: ci.submitted, reverse=True)
            if merged_change_infos:
              most_recent_uprev = merged_change_infos[0]
              presentation.logs[
                  'most recent merged cl'] = most_recent_uprev.display_id
          else:
            presentation.step_text = 'no merged CLs found'
            presentation.status = self.m.step.WARNING
    return most_recent_uprev

  def _get_outdated_cls(
      self,
      open_changes: List[GerritChange],
      most_recent_uprev: Optional[PatchSet],
  ) -> List[PatchSet]:
    """Query Gerrit to return all CLs older than the most recently merged.

    Args:
      open_changes: A list of currently open, relevant PUpr CLs.
      most_recent_uprev: The relevant uprev CL which was most recently merged.

    Returns:
      A list of CLs which were created before most_recent_uprev was either
      created or submitted. (We compare against most_recent_uprev's either
      created timestamp or submitted timestamp, depending on
      self.rebase_before_retry.)
    """
    if not most_recent_uprev:
      return []
    open_patch_sets = self.m.gerrit.fetch_patch_sets(open_changes)
    with self.m.step.nest('outdated CLs') as presentation:
      outdated_cls = [
          cl for cl in open_patch_sets
          if cl.created < self._get_outdated_timestamp(most_recent_uprev)
      ]
      presentation.logs['outdated CLs'] = [cl.display_id for cl in outdated_cls]
    return outdated_cls

  def _abandon_outdated_cls(self, outdated_cls: List[PatchSet],
                            obviating_uprev: PatchSet,
                            outdated_cls_policy: OutdatedClsPolicy,
                            retry_only_run: bool,
                            step_name: Optional[str] = None) -> List[PatchSet]:
    """Abandon uprev CLs according to the outdated_cls_policy.

    Args:
      outdated_cls: Open uprev CLs that are behind the most recent merge.
      obviating_uprev: The CL which makes outdated_cls outdated. Used for adding
        comments on the outdated CLs.
      outdated_cls_policy: This PUpr's policy for dealing with outdated CLs.
      retry_only_run: this weirdly named property only causes a run in
        `OUTDATED_LEAVE_COMMENT` mode to not actually leave a comment if true.
      step_name: Option to override the default step name for this method.

    Returns:
      List of CLs which have been abandoned.
    """
    if not outdated_cls:
      return []
    abandoned_cls: List[PatchSet] = []
    if step_name is None:
      step_name = 'act on outdated CLs with policy: {}'.format(
          OutdatedClsPolicy.Name(outdated_cls_policy))
    with self.m.step.nest(step_name):
      for outdated_cl in outdated_cls:
        if outdated_cls_policy == OUTDATED_LEAVE_COMMENT and not retry_only_run:
          outdated_comment_message = ('This CL has been obviated by: {}\n\n'
                                      'PUpr has been set to remind you that it'
                                      ' likely should be abandoned.').format(
                                          obviating_uprev.display_url)
          self.m.gerrit.add_change_comment_remote(
              outdated_cl.to_gerrit_change_proto(), outdated_comment_message)
        elif outdated_cls_policy == OUTDATED_ABANDON:
          outdated_comment_message = ('This CL has been obviated by: {}\n\n'
                                      'PUpr has been set to abandon.').format(
                                          obviating_uprev.display_url)
          self.m.gerrit.abandon_change(outdated_cl.to_gerrit_change_proto(),
                                       message=outdated_comment_message)
          abandoned_cls.append(outdated_cl)
    return abandoned_cls

  def create_uprev_cls(self, repo_projects: List[ProjectInfo],
                       open_changes: List[GerritChange], existing_cls: bool,
                       policy: BranchPolicy, topic: str) -> str:
    """Create appropriate CLs for the uprevs.

    Args:
      repo_projects: The projects to create uprev CLs for.
      open_changes: Open uprev CLs.
      existing_cls: Whether any open CLs remain after abandoning.
      policy: The branch policy set for the builder.
      topic: Gerrit topic name added to the Changes managed by this builder.

    Returns:
      Human-readable summary of the operation.
    """
    send_to_cq_policy = (
        policy.existing_cls_policy
        if existing_cls else policy.no_existing_cls_policy)

    limit_exceeded = False
    running_count = 0
    if (send_to_cq_policy in [DRY_RUN, DRY_RUN_NOT_APPROVED, FULL_RUN] and
        policy.max_concurrent_cq_runs > 0 and open_changes):
      with self.m.step.nest('check concurrent CQ runs') as presentation:
        open_patch_sets = self.m.gerrit.fetch_patch_sets(
            open_changes, include_messages=True, include_detailed_labels=True)
        limit_exceeded, running_count = self.m.pupr.check_concurrent_cq_limit(
            open_patch_sets, policy.max_concurrent_cq_runs)
        presentation.step_text = f'running: {running_count}, limit: {policy.max_concurrent_cq_runs}'

    with self.m.step.nest('generate CLs'):
      changes = []
      for project in sorted(repo_projects):
        is_repo = False
        try:
          self.m.path.abs_to_path(project.path)
        except ValueError:  # pragma: no cover
          with self.m.context(cwd=self.workspace_path):  # pragma: no cover
            if self.m.repo.project_exists(project.path):  # pragma: no cover
              is_repo = True  # pragma: no cover
        if is_repo:
          cwd = self.workspace_path / project.path  # pragma: no cover
        else:
          cwd = self.m.path.abs_to_path(project.path)

        changes.append(
            self.m.gerrit.create_change(
                project.path,
                reviewers=[reviewer.email for reviewer in policy.reviewers],
                topic=topic,
                project_path=None if is_repo else cwd,
                non_repo_checkout=not is_repo,
            ))
      self.m.easy.set_properties_step(
          generated_cls=[MessageToDict(change) for change in changes])

    if changes:
      with self.m.step.nest('cq-depend generated CLs'):
        cq_depends = self.m.cros_cq_depends.get_mutual_cq_depend(changes)
        for change, cq_depend in zip(changes, cq_depends):
          with self.m.step.nest('set cq-depend for {} CL'.format(
              change.project)) as presentation:
            if not cq_depend:
              presentation.step_text = 'empty Cq-Depend, skipping'
              continue
            description = self.m.gerrit.get_change_description(change)
            description = self.m.git_footers.edit_add_change_description(
                description, 'Cq-Depend', cq_depend)
            self.m.gerrit.set_change_description(change, description,
                                                 amend_local=True)

    with self.m.step.nest('update CL labels'):
      for change in changes:
        # First post explanatory message.
        message_lines = [
            'Found {} open CL(s) for Gerrit topic {}:'.format(
                len(open_changes), topic),
            '\n'.join(map(self.m.gerrit.parse_gerrit_change_url, open_changes)),
            'Send-to-cq policy for this case is {}.'.format(
                SendToCqPolicy.Name(send_to_cq_policy))
        ]

        message_lines.append({
            DRY_RUN:
                'Therefore, marking CL as CQ+1',
            DRY_RUN_NOT_APPROVED:
                'Therefore, marking CL as CQ+1 without Bot-Commit',
            FULL_RUN:
                'Therefore, marking CL as CQ+2',
            ABANDON:
                'Therefore, abandoning the CL',
            SUBMIT:
                'Therefore, will attempt to directly submit the CL.',
        }.get(
            send_to_cq_policy,
            'Therefore, will NOT mark CL as CQ+1/CQ+2. Reviewers must do so. '
            'Reviewers may also want to abandon the open CL(s).',
        ))

        if limit_exceeded:
          message_lines.append(
              'However, the concurrent CQ run limit of {} has been reached or exceeded '
              '(currently running: {}). Therefore, this CL will NOT be set to CQ.'
              .format(policy.max_concurrent_cq_runs, running_count))

        message = '\n'.join(message_lines)
        if send_to_cq_policy == ABANDON:
          self.m.gerrit.abandon_change(change, message=message)
        else:
          self.m.gerrit.add_change_comment_remote(change, message)

        # Then set labels.
        labels = {
            DRY_RUN: {
                Label.BOT_COMMIT: 1,
                Label.COMMIT_QUEUE: 0 if limit_exceeded else 1,
            },
            DRY_RUN_NOT_APPROVED: {
                Label.COMMIT_QUEUE: 0 if limit_exceeded else 1,
            },
            FULL_RUN: {
                Label.BOT_COMMIT: 1,
                Label.COMMIT_QUEUE: 0 if limit_exceeded else 2,
            },
            SUBMIT: {
                Label.BOT_COMMIT: 1,
            },
        }.get(send_to_cq_policy, {})
        if self.m.cros_infra_config.is_staging:
          labels.pop(Label.BOT_COMMIT, None)
        if policy.cr_policy == CR_REJECT:
          labels[Label.CODE_REVIEW] = -2
        if labels:
          self.m.gerrit.set_change_labels_remote(change, labels)

        if send_to_cq_policy == SUBMIT:
          with self.m.step.nest('submit CL'):
            self.m.gerrit.submit_change(change)

      def gerrit_url(c: GerritChange) -> str:
        if c.host == 'chromium-review.googlesource.com':
          return f'[chromium:{c.change}](https://crrev.com/c/{c.change})'
        if c.host == 'chrome-internal-review.googlesource.com':
          return f'[chrome-internal:{c.change}](https://crrev.com/i/{c.change})'
        return str(c.change)

      return 'created ' + ' '.join(gerrit_url(c) for c in changes)

  def upload_new_patch_set(self, gerrit_patch_set: PatchSet,
                           title: Optional[str] = None,
                           description: Optional[str] = None):
    """Upload a new revision onto an existing Gerrit PatchSet."""
    step_name = f'upload patch set for Change-Id {gerrit_patch_set.change_id}'
    with self.m.step.nest(step_name), self.m.context(cwd=self.workspace_path):
      gerrit_change = gerrit_patch_set.to_gerrit_change_proto()
      project = self.m.repo.project_info(gerrit_change.project)
      repo_path = self.m.path.join(self.workspace_path, project.path)
      with self.m.context(cwd=self.m.path.abs_to_path(repo_path)):
        self.m.git_cl.upload(send_mail=True, title=title,
                             description=description)

  def retry_cl(self, patch_set: PatchSet, cq_label: int):
    """Retry sending the CL through CQ by setting its Gerrit labels."""
    with self.m.step.nest('retry CL {}'.format(patch_set.change_id)):
      labels = {
          Label.COMMIT_QUEUE: cq_label,
      }
      if cq_label > 1:
        # Only ensure Bot-Commit +1 if cq_label is CQ+2
        # Some dry-run SendToCqPolicy does not vote Bot-Commit by default.
        # Bot-Commit will only be ensured if we really want to submit this CL.
        # For example, a FULL_RUN CL, or DRY_RUN_NOT_APPROVED approved by
        # someone/sometask else.
        labels[Label.BOT_COMMIT] = 1
      if self.m.cros_infra_config.is_staging:
        labels.pop(Label.BOT_COMMIT, None)
      gerrit_change = patch_set.to_gerrit_change_proto()
      self.m.gerrit.set_change_labels_remote(gerrit_change, labels)

  def apply_retry_policy(self, open_changes: List[GerritChange],
                         most_recent_uprev: Optional[PatchSet],
                         policy: BranchPolicy, topic: str,
                         retry_only_run: bool):
    """Retry any open uprev CLs based on the retry policy.

    Args:
      open_changes: A list of currently open, relevant PUpr CLs.
      most_recent_uprev: The most recently merged uprev CL.
      policy: The policy selected by this PUpr run.
      topic: A short string with which to tag all generated uprev commits.
      retry_only_run: this weirdly named property only causes a run in
        `OUTDATED_LEAVE_COMMENT` mode to not actually leave a comment if true.
    """
    if policy.retry_cl_policy == NO_RETRY:
      return
    with self.m.step.nest('apply retry policy {}'.format(
        RetryClPolicy.Name(policy.retry_cl_policy))) as presentation:
      if not open_changes:
        return
      open_patch_sets = self.m.gerrit.fetch_patch_sets(
          open_changes, include_messages=True, include_detailed_labels=True)
      if most_recent_uprev:
        open_patch_sets = [
            ps for ps in open_patch_sets
            if ps.created > self._get_outdated_timestamp(most_recent_uprev)
        ]
      if self.m.pupr.retries_frozen(open_patch_sets):
        return

      patch_set_to_retry, cq_label, message, cl_passed_dry_run, running = \
          self.m.pupr.identify_retry(policy.retry_cl_policy,
                                     policy.no_existing_cls_policy,
                                     open_patch_sets)
      presentation.step_text = message

      if not patch_set_to_retry:
        return
      if self.rebase_before_retry:
        changes_to_retry = [
            change for change in open_changes
            if change.host == patch_set_to_retry.host and
            change.change == patch_set_to_retry.change_id
        ]
        with self.m.step.nest('test gerrit mergeable'):
          gerrit_mergeable = self.m.gerrit.get_change_mergeable(
              patch_set_to_retry.change_id, patch_set_to_retry.host)
        with self.m.step.nest('test cq-orchestrator mergeable') as cqstep:
          cq_mergable = self.m.gerrit.changes_submittable(changes_to_retry)
          # gerrit.changes_submittable generates non-critical StepFailure.
          # Set cqstep.status to SUCCESS to avoid parent being StepFailure
          cqstep.status = 'SUCCESS'
        if gerrit_mergeable and not cq_mergable:
          self.m.gerrit.rebase_change_remote(changes_to_retry[0])
          self.m.gerrit.add_change_comment_remote(
              changes_to_retry[0],
              ('[Auto-Rebase] Rebased via Gerrit to save CQ time. '
               'Previously passed CQ results will be reused. '
               'It is completely expected for this changeset to now '
               'show as an `add` instead of a `rename`.'))
          # A rebase resets the CQ+1/+2 status.
          running = False
        elif not gerrit_mergeable:
          self.m.pupr_local_uprev.rebase_cl(open_changes, topic,
                                            patch_set_to_retry.change_id)
          title = 'rebased by {}'.format(self.m.buildbucket.build_url())
          self.upload_new_patch_set(patch_set_to_retry, title=title,
                                    description='+')
          self.m.gerrit.add_change_comment_remote(
              changes_to_retry[0], ('[Rebase] A rebased CL is uploaded. '
                                    'CQ will need to rerun everything.'))
          # A new patchset upload resets CQ+1/+2 status.
          running = False

      if running:
        # Already running for CQ. No need to retry.
        return

      if policy.max_concurrent_cq_runs > 0:
        limit_exceeded, running_count = self.m.pupr.check_concurrent_cq_limit(
            open_patch_sets, policy.max_concurrent_cq_runs)
        if limit_exceeded:
          presentation.step_text = (
              f'{message} (Retry skipped: concurrent CQ run limit of '
              f'{policy.max_concurrent_cq_runs} reached, currently running: {running_count})'
          )
          return

      self.retry_cl(patch_set_to_retry, cq_label)

      if cl_passed_dry_run:
        cls_to_abandon = [cl for cl in open_patch_sets \
            if cl.created < patch_set_to_retry.created]
        self._abandon_outdated_cls(
            cls_to_abandon, patch_set_to_retry, policy.outdated_cls_policy,
            retry_only_run, step_name='abandon CLs before passed CQ+1 CL')

  def _get_outdated_timestamp(self, most_recent_uprev: PatchSet) -> str:
    """Determine the cutoff time at which CLs become outdated.

    Args:
      most_recent_uprev: The most recently merged relevant uprev.

    Returns:
      A timestamp string, in the same format as PatchSet.created, after which
      any CL would be considered outdated.
    """
    if self.rebase_before_retry:
      return most_recent_uprev.created
    return most_recent_uprev.submitted
