# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for running cbuildbot chromite scripts."""

import base64
import re
import xml.etree.ElementTree as ET

from recipe_engine import recipe_api

TEST_MANIFEST = b'''<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="_remotes.xml" />
  <default revision="refs/heads/main"
           remote="cros"
           sync-j="8" />
  <project path="src/chromium/depot_tools"
           remote="chromium"
           name="chromium/tools/depot_tools"
           revision="c49a7334d30256abc1fc1e56d79615a220028998"
           groups="minilayout,firmware,buildtools,labtools" />
</manifest>
'''


class ChromiteApi(recipe_api.RecipeApi):
  chromite_url = 'https://chromium.googlesource.com/chromiumos/chromite.git'
  depot_tools_url = (
      'https://chromium.googlesource.com/chromium/tools/depot_tools.git')
  _depot_tools_pin = None

  # Only used by the internal goma recipe.
  manifest_host = 'chromium.googlesource.com'
  manifest_project = 'chromiumos/manifest'
  manifest_url = 'https://{}/{}.git'.format(manifest_host, manifest_project)
  repo_url = 'https://chromium.googlesource.com/external/repo.git'

  # The number of Gitiles attempts to make before giving up.
  _GITILES_ATTEMPTS = 10

  _MANIFEST_CMD_RE = re.compile(r'Automatic:\s+Start\s+([^\s]+)\s+([^\s]+)')
  _BUILD_ID_RE = re.compile(r'CrOS-Build-Id: (.+)')

  @property
  def depot_tools_pin(self):
    if self._depot_tools_pin:
      return self._depot_tools_pin
    with self.m.step.nest('fetch depot_tools pin from manifest'):
      tot_manifest = self.m.cros_gitiles.get_file(
          self.manifest_host, self.manifest_project, 'full.xml',
          test_output_data=base64.b64encode(TEST_MANIFEST))
      root = ET.fromstring(tot_manifest)
      self._depot_tools_pin = root.findall(
          './/project[@path="src/chromium/depot_tools"]')[0].attrib['revision']
    return self._depot_tools_pin

  @property
  def chromite_path(self):
    return self.m.path['start_dir'].join('chromite')

  @property
  def depot_tools_path(self):
    return self.m.path['start_dir'].join('depot_tools')

  @property
  def chromite_branch(self):
    return self.c.chromite_branch

  def get_config_defaults(self):
    defaults = {
        'CBB_CONFIG': self.m.properties.get('cbb_config'),
        'CBB_BRANCH': self.m.properties.get('cbb_branch'),
        'CBB_MAIN_BUILD_ID': self.m.properties.get('cbb_master_build_id'),
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

  def gclient_config(self):
    """Generate a 'gclient' configuration to check out Chromite.

    Return: (config) A 'gclient' recipe module configuration.
    """
    cfg = self.m.gclient.make_config()
    soln = cfg.solutions.add()
    soln.name = 'chromite'
    soln.url = self.chromite_url
    soln.revision = 'main'

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
    kwargs['legacy_global_namespace'] = True
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

    kwarg_list = ['%s=%s' % kwarg for kwarg in kwargs.items()]

    return self.m.step(name, ['python3', chroot_cmd] + arg_list + kwarg_list)

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

  def configure(self, **kwargs) -> None:
    """Loads configuration from build properties into this recipe config."""
    self.set_config('main_swarming', **kwargs)

  def checkout_chromite(self):
    """Checks out the configured Chromite branch.
    """
    self.m.bot_update.ensure_checkout(gclient_config=self.gclient_config(),
                                      update_presentation=False,
                                      ignore_input_commit=True,
                                      set_output_commit=False)

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

  def run(self, goma_dir=None):
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

    cbb_args = []
    cbb_args.extend(
        ['--buildroot', self.m.path['cleanup'].join('snapshot', 'chromeos')])
    cbb_args.extend(['--workspace', self.m.path['cleanup'].join('workspace')])
    cbb_args.extend(['--source_cache'])

    if self.c.chromite_branch:
      cbb_args.extend(['--branch', self.c.chromite_branch])
    if self.c.cbb.build_number is not None:
      cbb_args.extend(['--buildnumber', self.c.cbb.build_number])
    if self.c.cbb.debug:
      cbb_args.extend(['--debug'])  # pragma: nocover
    if self.c.cbb.clobber:
      cbb_args.extend(['--clobber'])
    if self.c.cbb.chrome_version:
      cbb_args.extend(['--chrome_version', self.c.cbb.chrome_version])
    if self.c.cbb.buildbucket_id:
      cbb_args.extend(['--buildbucket-id', self.c.cbb.buildbucket_id])
    # Set the CIDB main build ID, if specified.
    if self.c.cbb.build_id:
      cbb_args.extend(['--master-build-id', self.c.cbb.build_id])

    if goma_dir is None:
      goma_dir = self.m.goma.goma_dir

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
