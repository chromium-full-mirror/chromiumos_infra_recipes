# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from recipe_engine import recipe_api


class ChromiteApi(recipe_api.RecipeApi):
  chromite_url = 'https://chromium.googlesource.com/chromiumos/chromite.git'
  depot_tools_url = (
      'https://chromium.googlesource.com/chromium/tools/depot_tools.git')
  # Keep this pin in sync with manifest pin in:
  #   https://chromium.googlesource.com/chromiumos/manifest/+/master/full.xml
  depot_tools_pin = 'fdd2cd6e5fc0c1e5584fc1136043f9509615f817'

  # Only used by the internal goma recipe.
  manifest_url = 'https://chromium.googlesource.com/chromiumos/manifest.git'
  repo_url = 'https://chromium.googlesource.com/external/repo.git'

  # The number of Gitiles attempts to make before giving up.
  _GITILES_ATTEMPTS = 10

  _MANIFEST_CMD_RE = re.compile(r'Automatic:\s+Start\s+([^\s]+)\s+([^\s]+)')
  _BUILD_ID_RE = re.compile(r'CrOS-Build-Id: (.+)')

  @property
  def chromite_path(self):
    return self.m.path['start_dir'].join('chromite')

  @property
  def depot_tools_path(self):
    return self.m.path['start_dir'].join('depot_tools')

  def get_config_defaults(self):
    defaults = {
        'CBB_CONFIG': self.m.properties.get('cbb_config'),
        'CBB_BRANCH': self.m.properties.get('cbb_branch'),
        'CBB_MASTER_BUILD_ID': self.m.properties.get('cbb_master_build_id'),
        'CBB_DEBUG': self.m.properties.get('cbb_debug') is not None,
        'CBB_CLOBBER': 'clobber' in self.m.properties,
    }
    if self.m.buildbucket.build.number:
      defaults['CBB_BUILD_NUMBER'] = self.m.buildbucket.build.number

    build_id = self.m.buildbucket.build.id
    if build_id:
      defaults['CBB_BUILDBUCKET_ID'] = build_id

    return defaults

  def check_repository(self, repo_type_key, value):
    """Scans through registered repositories for a specified value.

    Args:
      repo_type_key (str): The key in the 'repositories' config to scan through.
      value (str): The value to scan for.
    Returns (bool): True if the value was found.
    """
    for v in self.c.repositories.get(repo_type_key, ()):
      if v == value:
        return True
    return False

  def load_manifest_config(self, repository, revision):
    """Loads manifest-specified parameters from the manifest commit.

    This method parses the commit log for the following information:
    - The branch to build (From the "Automatic": tag).
    - The build ID (from the CrOS-Build-Id: tag).

    Args:
      repository (str): The URL of the repository hosting the change.
      revision (str): The revision hash to load the build ID from.
    """
    if all((self.c.chromite_branch, self.c.cbb.build_id)):
      # They have all already been populated, so we're done (BuildBucket).
      return

    # Load our manifest fields from the formatted Gitiles commit message that
    # scheduled this build.
    #
    # First, check that we are actually in a known manifest Gitiles repository.
    if not self.check_repository('cros_manifest', repository):
      return

    commit_log = self.m.gitiles.commit_log(repository, revision,
                                           step_name='Fetch manifest config',
                                           attempts=self._GITILES_ATTEMPTS)
    result = self.m.step.active_result

    # Handle missing/invalid response.
    if not (commit_log and commit_log.get('message')):
      self.m.python.failing_step('Fetch manifest config failure',
                                 'Failed to fetch manifest config.')

    loaded = []
    for line in reversed(commit_log['message'].splitlines()):
      # Automatic command?
      match = self._MANIFEST_CMD_RE.match(line)
      if match:
        self.c.chromite_branch = match.group(2)
        loaded.append('Chromite branch: %s' % (self.c.chromite_branch,))
        continue

      # Build ID?
      match = self._BUILD_ID_RE.match(line)
      if match:
        self.c.cbb.build_id = match.group(1)
        continue
    if loaded:
      loaded.insert(0, '')
      result.presentation.step_text += '<br/>'.join(loaded)

  def gclient_config(self):
    """Generate a 'gclient' configuration to check out Chromite.

    Return: (config) A 'gclient' recipe module configuration.
    """
    cfg = self.m.gclient.make_config()
    soln = cfg.solutions.add()
    soln.name = 'chromite'
    soln.url = self.chromite_url
    soln.revision = 'master'

    soln = cfg.solutions.add()
    soln.name = 'depot_tools'
    soln.url = self.depot_tools_url
    soln.revision = self.depot_tools_pin

    return cfg

  def cbuildbot(self, name, config, args=None, **kwargs):
    """Runs the cbuildbot command defined by the arguments.

    Args:
      name: (str) The name of the command step.
      config: (str) The name of the 'cbuildbot' configuration to invoke.
      args: (list) If not None, addition arguments to pass to 'cbuildbot'.

    Returns: (Step) The step that was run.
    """
    args = (args or [])[:]
    args.append(config)

    cmd = [self.chromite_path.join('scripts', 'cbuildbot_launch')] + args
    return self.m.legacy_annotation(name, cmd, **kwargs)

  # Only used by the internal goma recipe.
  def checkout(self, manifest_url=None, repo_url=None, branch=None):
    manifest_url = manifest_url or self.manifest_url
    repo_url = repo_url or self.repo_url

    if branch:
      self.m.repo.init(manifest_url=repo_url, manifest_branch=branch)
    else:
      self.m.repo.init(manifest_url=repo_url)
    self.m.repo.sync()

  # Only used by the internal goma recipe.
  def cros_sdk(self, name, cmd, args=None, environ=None, chroot_cmd=None,
               **kwargs):
    """Return a step to run a command inside the cros_sdk.

    Used by the internal goma recipe.
    """
    if not chroot_cmd:
      chroot_cmd = self.chromite_path.join('bin', 'cros_sdk')

    arg_list = (args or [])[:]
    for t in sorted((environ or {}).items()):
      arg_list.append('%s=%s' % t)
    arg_list.append('--')
    arg_list.extend(cmd)

    return self.m.python(name, chroot_cmd, arg_list, **kwargs)

  # Only used by the internal goma recipe.
  def setup_board(self, board, args=None, **kwargs):
    """Run the setup_board script inside the chroot.

    Used by the internal goma recipe.
    """
    self.cros_sdk('setup board', ['./setup_board', '--board', board], args,
                  **kwargs)

  # Only used by the internal goma recipe.
  def build_packages(self, board, args=None, **kwargs):
    """Run the build_packages script inside the chroot.

    Used by the internal goma recipe.
    """
    self.cros_sdk('build packages', ['./build_packages', '--board', board],
                  args, **kwargs)

  def configure(self, properties, config_map, **KWARGS):
    """Loads configuration from build properties into this recipe config.

    Args:
      properties (Properties): The build properties object.
      config_map (dict): The configuration map to use.
      KWARGS: Additional keyword arguments to forward to the configuration.
    """
    builder_group = self.m.cros_infra_config.current_builder_group
    builder = self.m.buildbucket.builder_name

    if builder_group is None:
      self.set_config('master_swarming', **KWARGS)
      return

    # Set the groups's base configuration.
    config_map = config_map.get(builder_group, {})
    group_config = config_map.get('group_config')
    assert group_config, ("No 'group_config' configuration for '%s'" %
                          (builder_group,))
    self.set_config(group_config, **KWARGS)

    # Set per-builder configuration if any.
    builder_config = config_map.get('builder_config', {}).get(builder, None)
    if builder_config:
      self.set_config(builder_config, **KWARGS)

  def run_cbuildbot(self, args=None, goma_canary=False):
    """Performs a Chromite repository checkout, then runs cbuildbot.

    Args:
      args (list): Initial argument list, see run() for details.
      goma_canary (bool): Use canary version of goma if True.
    """
    # Fetch chromite and depot_tools.
    self.checkout_chromite()

    # Update or install goma client via cipd.
    client_type = None
    if goma_canary:
      client_type = 'candidate'
    self.m.goma.initialize()
    self.m.goma.client_version = client_type

    self.run(args)

  def checkout_chromite(self):
    """Checks out the configured Chromite branch.
    """
    self.m.bot_update.ensure_checkout(gclient_config=self.gclient_config(),
                                      update_presentation=False,
                                      ignore_input_commit=True)

    return self.chromite_path

  def with_system_python(self):
    """Prepare a directory with the system python binary available.

    This is designed to make it possible to mask "bundled python" out of the
    standard path without hiding any other binaries.

    Returns: (context manager) A context manager that inserts system python
        into the front of PATH.
    """
    with self.m.step.nest('system_python'):
      # Create a directory to hold a symlink to the system python binary.
      python_bin = self.m.path['start_dir'].join('python_bin')
      self.m.file.ensure_directory('create_dir', python_bin)

      # Remove any old symlinks.
      self.m.file.remove('remove_link', python_bin.join('python'))
      self.m.file.remove('remove_link', python_bin.join('python2'))

      # Create a symlink to the system python binary in that directory.
      self.m.file.symlink('create_link', '/usr/bin/python',
                          python_bin.join('python'))
      self.m.file.symlink('create_link', '/usr/bin/python2',
                          python_bin.join('python2'))

    # python2 a context manager to insert that directory at the front of PATH.
    return self.m.context(env_prefixes={'PATH': [python_bin]})

  def run(self, args=None, goma_dir=None):
    """Runs the configured 'cbuildbot' build.

    This workflow uses the registered configuration dictionary to make group-
    and builder-specific changes to the standard workflow.

    The specific workflow paths that are taken are also influenced by several
    build properties.

    TODO(dnj): When CrOS migrates away from BuildBot, replace property
        inferences with command-line parameters.

    This workflow:
    - Checks out the specified 'cbuildbot' repository.
    - Pulls information based on the configured change's repository/revision
      to pass to 'cbuildbot'.
    - Executes the 'cbuildbot' command.

    Args:
      args (list): Initial argument list, expanded based on other values.
      goma_dir: Goma client path used for simplechrome.
                Goma client for ChromeOS chroot should be located in sibling
                directory so that cbuildbot can find it automatically.
    Returns: (Step) the 'cbuildbot' execution step.
    """
    # Assert correct configuration.
    assert self.c.cbb.config, 'An empty configuration was specified.'

    # Load properties from the commit being processed. This requires both a
    # repository and revision to proceed.
    repository = self.m.tryserver.gerrit_change_repo_url
    revision = self.m.buildbucket.gitiles_commit.id
    if repository and revision:
      # Pull more information from the commit if it came from certain known
      # repositories.
      if (self.c.use_chrome_version and
          self.check_repository('chromium', repository)):
        # If our change comes from a Chromium repository, add the
        # '--chrome_version' flag.
        self.c.cbb.chrome_version = self.m.buildbucket.gitiles_commit.id

      # This change comes from a manifest repository. Load configuration
      # parameters from the manifest command.
      self.load_manifest_config(repository, revision)

    cbb_args = [
        '--buildroot',
        self.m.path['cache'].join('cbuild'),
    ]

    if args:
      cbb_args.extend(args)
    if self.c.chromite_branch:
      cbb_args.extend(['--branch', self.c.chromite_branch])
    if self.c.cbb.build_number is not None:
      cbb_args.extend(['--buildnumber', self.c.cbb.build_number])
    if self.c.cbb.debug:
      cbb_args.extend(['--debug'])
    if self.c.cbb.clobber:
      cbb_args.extend(['--clobber'])
    if self.c.cbb.chrome_version:
      cbb_args.extend(['--chrome_version', self.c.cbb.chrome_version])
    if self.c.cbb.buildbucket_id:
      cbb_args.extend(['--buildbucket-id', self.c.cbb.buildbucket_id])
    # Set the CIDB master build ID, if specified.
    if self.c.cbb.build_id:
      cbb_args.extend(['--master-build-id', self.c.cbb.build_id])

    cbb_args.extend(['--git-cache-dir', self.m.path['cache'].join('git')])
    # Use preloaded chrome cache present on the nightly image for chrome sync.
    cbb_args.extend(['--chrome-preload-dir', '/preload/chrome_cache'])

    if goma_dir is None:
      goma_dir = self.m.goma.goma_dir
    cbb_args.extend(['--goma_dir', goma_dir])

    # Add custom args, if there are any.
    cbb_args.extend(self.c.cbb.extra_args)

    # Run cbuildbot.
    # TODO(dgarrett): stop adjusting path here, and pass into cbuildbot_launcher
    # instead.
    #
    # Set "DEPOT_TOOLS_UPDATE" to prevent any invocations of "depot_tools"
    # scripts that call "//update_depot_tools" (e.g., "gclient") from trying
    # to self-update from their pinned version (crbug.com/736890).
    ctx = {
        'cwd': self.m.path['start_dir'],
        'env_suffixes': {
            'PATH': [self.depot_tools_path]
        },
        'env': {
            'DEPOT_TOOLS_UPDATE': '0'
        }
    }
    with self.m.context(**ctx):
      return self.cbuildbot(
          str('cbuildbot_launch [%s]' % (self.c.cbb.config,)),
          self.c.cbb.config, args=cbb_args)
