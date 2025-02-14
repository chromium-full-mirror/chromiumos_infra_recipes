# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Checks a project conforms to its program's constraints."""

from PB.recipes.chromeos.check_project_config import CheckProjectConfigProperties
from PB.recipes.chromeos.check_project_config import ConfigBundleCheckoutPath
from recipe_engine import post_process

PROPERTIES = CheckProjectConfigProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_source',
    'gerrit',
    'gs_step_logging',
    'repo',
    'src_state',
    'workspace_util',
]



def RunSteps(api, properties):
  # Because we use workspace_util to handle the source checkout, we need to call
  # configure_builder even though we don't have a builder config.
  commit = api.src_state.gitiles_commit
  if not commit.project:
    commit = (api.src_state.external_manifest
              if properties.use_external_manifest else
              api.src_state.internal_manifest).as_gitiles_commit_proto
  api.cros_source.configure_builder(commit=commit,
                                    changes=api.src_state.gerrit_changes)

  if not properties.manifest_groups:
    raise ValueError('At least one manifest group must be specified.')

  if not api.buildbucket.build.input.gerrit_changes:
    raise ValueError('At least one gerrit_change must be specified.')

  if not all((
      properties.chromiumos_config_checkout_path,
      properties.program_config_bundle_checkout_path.repo_checkout_path,
      properties.program_config_bundle_checkout_path.config_path,
      properties.project_config_bundle_checkout_path.repo_checkout_path,
      properties.project_config_bundle_checkout_path.config_path,
  )):
    raise ValueError('All checkout_paths and config_paths must be specified.')

  local_manifests = []
  for lm in properties.local_manifests:
    local_manifests.append(
        api.repo.LocalManifest(repo=lm.repo_url, path=lm.manifest_path,
                               branch=properties.manifest_branch))

  if not local_manifests and not properties.manifest_branch:
    raise ValueError('local_manifests must be specified')

  # Do work in a context with manifest groups checked out. Most steps are infra
  # steps, so make this the default. Non-infra steps specify this explicitly.
  # Note the overriding of the cache path in the sync_to_manifest_groups call.
  # This is done because these checkouts are much smaller than a full checkout
  # and thus skipping the standard cache avoids a costly time sink of deleting
  # unused repos.
  with api.context(infra_steps=True), \
      api.workspace_util.sync_to_manifest_groups(
          properties.manifest_groups,
          local_manifests=local_manifests,
          cache_path_override=api.src_state.workspace_path,
          manifest_branch=properties.manifest_branch):
    api.workspace_util.apply_changes(api.buildbucket.build.input.gerrit_changes,
                                     ignore_missing_projects=True)

    chromiumos_config_path = properties.chromiumos_config_checkout_path

    generate_path = api.path.join(api.context.cwd, chromiumos_config_path,
                                  'generate.sh')
    checker_path = api.path.join(api.context.cwd, chromiumos_config_path,
                                 'payload_utils/checker.py')

    # mock_add_paths marks that the path exists for tests. The exists call
    # doesn't actually perform a Recipes step, it just calls the standard
    # Python os.exists (and in testing it calls a fake implementation of
    # os.exists). Thus, this mocking can't be done in GenTests. This also means
    # there isn't a good way to create a test case that triggers the failure
    # case.
    api.path.mock_add_paths(generate_path)
    api.path.mock_add_paths(checker_path)

    if not api.path.exists(generate_path):  # pragma: nocover
      raise api.step.InfraFailure('generate.sh not found. Expected at %s' %
                                  generate_path)

    if not api.path.exists(checker_path):  #pragma: nocover
      raise api.step.InfraFailure('Checker not found. Expected at %s' %
                                  checker_path)

    api.step('generate proto bindings', [generate_path])

    program_path = api.path.join(
        api.context.cwd,
        properties.program_config_bundle_checkout_path.repo_checkout_path,
        properties.program_config_bundle_checkout_path.config_path)

    project_path = api.path.join(
        api.context.cwd,
        properties.project_config_bundle_checkout_path.repo_checkout_path,
        properties.project_config_bundle_checkout_path.config_path)

    factory_dir = api.path.join(
        api.context.cwd,
        properties.project_config_bundle_checkout_path.repo_checkout_path,
        properties.factory_dir,
    )

    # Call checker with checked out program and project. Note that a failure
    # here is not considered an infra failure. infra_steps set in context takes
    # precedent over infra_step passed to api.step, so need to create a new
    # context here.
    with api.context(
        infra_steps=False,
    ), api.gs_step_logging.log_step_to_gs(
        properties.logging_gs_prefix,
    ):
      checker_args = [
          '--program', program_path, '--project', project_path, '--factory_dir',
          factory_dir
      ]
      api.step(
          'check constraints',
          [checker_path] + checker_args,
          stdout=api.raw_io.output(add_output_log=True),
      )


def GenTests(api):

  def properties_dict(extra_props=None):
    """Returns a dict of basic valid properties, updated with extra_props."""
    extra_props = extra_props or {}
    props = {
        'manifest_groups': ['partner-config'],
        'local_manifests': [
            {
                'repo_url': ('https://chrome-internal.googlesource.com'
                             '/chromeos/project/testproject1'),
                'manifest_path': 'local_manifest.xml',
            },
            {
                'repo_url': ('https://chrome-internal.googlesource.com'
                             '/chromeos/program/testprogram1'),
                'manifest_path': 'local_manifest.xml',
            },
        ],
        'chromiumos_config_checkout_path':
            'src/config',
        'program_config_bundle_checkout_path':
            ConfigBundleCheckoutPath(
                repo_checkout_path='src/program/testprogram',
                config_path='generated/config.binaryproto',
            ),
        'project_config_bundle_checkout_path':
            ConfigBundleCheckoutPath(
                repo_checkout_path='src/project/testproject',
                config_path='generated/config.binaryproto',
            ),
        'logging_gs_prefix':
            'testprogram-testproject/cq_logs',
        'factory_dir':
            'factory',
    }
    props.update(extra_props)
    return props

  def project_config_cq_build(api):
    """Returns a sample buildbucket project config cq build"""
    return api.buildbucket.try_build(
        project='chromeos',
        bucket='testprogram-testproject',
        builder='config-checker-testprogram-testproject',
        git_repo='https://chrome-internal.googlesource.com/project1',
    )

  def checked_out_projects(api):
    """Returns StepData for the command used to find checked out projects.

    Note that the project name lines up with the project specified by
    project_config_cq_build.
    """
    return api.repo.project_infos_step_data(
        'cherry-pick gerrit changes.apply gerrit patch sets', [{
            'project': 'project1'
        }])

  def check_constraints_with_output():
    """Returns StepData for a check constraints step with stdout."""
    return api.step_data(
        'check constraints',
        stdout=api.raw_io.output('Test stdout from constraint checker'))

  yield api.test(
      'basic',
      api.properties(**properties_dict()),
      project_config_cq_build(api),
      # The input GerritChange is in a checked out project.
      checked_out_projects(api),
      check_constraints_with_output(),
      api.post_process(post_process.StepCommandContains,
                       'ensure synced checkout.repo init',
                       ['--groups', 'partner-config']),
      # The change should be applied.
      api.post_process(
          post_process.StepCommandContains,
          'cherry-pick gerrit changes.apply gerrit patch sets.git fetch',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/project1',
              'refs/changes/56/123456/7:',
          ],
      ),
  )

  yield api.test(
      'manifest-branch',
      api.properties(**properties_dict(extra_props={
          'manifest_branch': 'release-R123',
          'local_manifests': [],
      })),
      project_config_cq_build(api),
      # The input GerritChange is in a checked out project.
      checked_out_projects(api),
      check_constraints_with_output(),
      api.post_process(
          post_process.StepCommandContains, 'ensure synced checkout.repo init',
          ['--manifest-branch', 'release-R123', '--groups', 'partner-config']),
      # If manifest_branch is passed, an internal checkout should be used and no
      # local manifest should be used.
      api.post_process(post_process.DoesNotRunRE,
                       '.*fetch.*:local_manifest.xml'),
      # The change should be applied.
      api.post_process(
          post_process.StepCommandContains,
          'cherry-pick gerrit changes.apply gerrit patch sets.git fetch',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/project1',
              'refs/changes/56/123456/7:',
          ],
      ),
  )

  yield api.test(
      'local-manifest-missing',
      api.properties(**properties_dict(extra_props={
          'local_manifests': [],
      })),
      project_config_cq_build(api),
      api.expect_exception('ValueError'),
      api.post_process(post_process.SummaryMarkdownRE,
                       '.*local_manifests must be specified.*'),
      api.post_process(post_process.DropExpectation),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE')

  yield api.test(
      'local-manifest-and-manifest-branch-specified',
      api.properties(**properties_dict(extra_props={
          'manifest_branch': 'release-R123',
      })),
      project_config_cq_build(api),
      api.post_process(
          post_process.StepCommandContains, 'ensure synced checkout.repo init',
          ['--manifest-branch', 'release-R123', '--groups', 'partner-config']),
      api.post_process(
          post_process.StepCommandContains,
          'ensure synced checkout.fetch release-R123:local_manifest.xml', [
              '--url',
              'https://chrome-internal.googlesource.com/chromeos/project/testproject1/+/release-R123/local_manifest.xml'
          ]),
  )

  yield api.test(
      'checkout-paths-missing',
      api.properties(
          manifest_groups=['partner-config', 'testprogram-testproject'],
          chromiumos_config_checkout_path='src/config',
      ),
      project_config_cq_build(api),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.SummaryMarkdownRE,
          '.*All checkout_paths and config_paths must be specified.*'),
      api.post_process(post_process.DropExpectation),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE')

  yield api.test(
      'no-manifest-groups',
      api.expect_exception('ValueError'),
      api.post_process(post_process.SummaryMarkdownRE,
                       '.*At least one manifest group must be specified.*'),
      api.post_process(post_process.DropExpectation),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE')

  yield api.test(
      'no-gerrit-changes',
      api.properties(**properties_dict()),
      api.expect_exception('ValueError'),
      api.post_process(post_process.SummaryMarkdownRE,
                       '.*At least one gerrit_change must be specified.*'),
      api.post_process(post_process.DropExpectation),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE')

  yield api.test(
      'checker-failed',
      api.properties(**properties_dict()),
      project_config_cq_build(api),
      api.step_data('check constraints', retcode=1),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'cannot-access-gerrit-changes',
      api.properties(**properties_dict()),
      project_config_cq_build(api),
      # The input GerritChange is not in a checked out project. The discarded
      # changes are logged and the build succeeds.
      api.post_process(
          post_process.StepTextEquals,
          'cherry-pick gerrit changes.apply gerrit patch sets',
          'Discarded changes: chrome-internal:123456',
      ),
      api.post_process(post_process.DropExpectation),
  )
