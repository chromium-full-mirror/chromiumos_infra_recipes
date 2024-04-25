# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module for inter-process communication."""

from typing import Dict, List, Optional

from recipe_engine import recipe_api


class IPCApi(recipe_api.RecipeApi):

  def initialize(self):
    self._args = None
    self._bin = None
    self._version = 'latest'

  def make_subscription(self, topic: str, sub_name: str) -> None:
    """Create a subscription within a topic

    Args:
      topic: Pubsub topic name.
      sub_name: Pubsub subscription name.
    """
    self._execute('setup', ['-topic', topic, '-sub-name', sub_name])

  def send(self, topic: str, message_body: bytes,
           attributes: Optional[Dict[str, str]] = None) -> None:
    """Send a pubsub message on the given topic.

    Args:
      topic: Pubsub topic name.
      message_body: Message to send.
      attributes: dict encoding a 'subtopic'; subscribers, will take no action
        on messages outside their subtopic.
    """
    if attributes:
      attributes = {}
    json_attributes = self.m.json.input(attributes)

    self._execute('publish', [
        '-topic', topic, '-file', '/dev/stdin', '-attributes', json_attributes
    ], stdin_data=message_body)

  def receive(self, topic: str, sub_name: str,
              filter_attributes: Dict[str, str] = None) -> bytes:
    """Receive one message from the filtered subscription specified.

    Args:
      topic: Pubsub topic name.
      sub_name: Pubsub subscription name.
      filter_attributes: dict encoding a 'subtopic';
        messages which do not include the required attributes will be
        acknowledged but the message body will be ignored.
    Returns:
      The message body.
    """
    if not filter_attributes:
      filter_attributes = {}
    json_filter = self.m.json.input(filter_attributes)
    return self._execute(
        'subscribe',
        ['-topic', topic, '-sub-name', sub_name, '-attributes', json_filter])

  def _ensure_binary_present(self) -> None:
    """Ensure the IPC pubsub CLI is installed."""
    if self._bin:
      return

    with self.m.step.nest('ensure ipcpubsub exists'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path.start_dir.joinpath('cipd', 'ipcpubsub')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/ipcpubsub/${version}', self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._bin = cipd_dir / 'ipcpubsub'

  def _execute(self, subcommand: List[str], args: List[str],
               stdin_data: bytes = None) -> bytes:
    """Execute command with specified args"""
    self._ensure_binary_present()
    if not stdin_data:
      stdin_data = ''
    cmd = [self._bin, subcommand] + args
    return self.m.easy.stdout_step('ipc_pubsub: %s' % subcommand, cmd,
                                   infra_step=True,
                                   stdin=self.m.raw_io.input(stdin_data))
