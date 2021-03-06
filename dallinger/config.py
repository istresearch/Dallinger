from __future__ import unicode_literals

from collections import deque
from contextlib import contextmanager
from six.moves import configparser
import distutils.util
import logging
import os
import six
import sys

logger = logging.getLogger(__file__)

marker = object()

LOCAL_CONFIG = 'config.txt'
SENSITIVE_KEY_NAMES = (
    'access_id',
    'access_key',
    'password',
    'secret',
    'token',
)

default_keys = (
    ('ad_group', six.text_type, []),
    ('approve_requirement', int, []),
    ('assign_qualifications', bool, []),
    ('auto_recruit', bool, []),
    ('aws_access_key_id', six.text_type, [], True),
    ('aws_region', six.text_type, []),
    ('aws_secret_access_key', six.text_type, [], True),
    ('base_payment', float, []),
    ('base_port', int, []),
    ('browser_exclude_rule', six.text_type, []),
    ('clock_on', bool, []),
    ('contact_email_on_error', six.text_type, []),
    ('dallinger_email_address', six.text_type, []),
    ('dallinger_email_password', six.text_type, [], True),
    ('database_size', six.text_type, []),
    ('database_url', six.text_type, []),
    ('description', six.text_type, []),
    ('duration', float, []),
    ('dyno_type', six.text_type, []),
    ('group_name', six.text_type, []),
    ('heroku_auth_token', six.text_type, [], True),
    ('heroku_team', six.text_type, ['team']),
    ('host', six.text_type, []),
    ('id', six.text_type, []),
    ('keywords', six.text_type, []),
    ('lifetime', int, []),
    ('logfile', six.text_type, []),
    ('loglevel', int, []),
    ('mode', six.text_type, []),
    ('notification_url', six.text_type, []),
    ('num_dynos_web', int, []),
    ('num_dynos_worker', int, []),
    ('organization_name', six.text_type, []),
    ('port', int, ['PORT']),
    ('qualification_blacklist', six.text_type, []),
    ('recruiter', six.text_type, []),
    ('recruiters', six.text_type, []),
    ('redis_size', six.text_type, []),
    ('replay', bool, []),
    ('threads', six.text_type, []),
    ('title', six.text_type, []),
    ('us_only', bool, []),
    ('webdriver_type', six.text_type, []),
    ('webdriver_url', six.text_type, []),
    ('whimsical', bool, []),
    ('sentry', bool, []),
)


class Configuration(object):

    SUPPORTED_TYPES = {
        six.binary_type,
        six.text_type,
        int,
        float,
        bool,
    }

    def __init__(self):
        self._reset()

    def set(self, key, value):
        return self.extend({key: value})

    def clear(self):
        self.data = deque()
        self.ready = False

    def _reset(self, register_defaults=False):
        self.clear()
        self.types = {}
        self.synonyms = {}
        self.sensitive = set()
        if register_defaults:
            for registration in default_keys:
                self.register(*registration)

    def extend(self, mapping, cast_types=False, strict=False):
        normalized_mapping = {}
        for key, value in mapping.items():
            key = self.synonyms.get(key, key)
            if key not in self.types:
                # This key hasn't been registered, we ignore it
                if strict:
                    raise KeyError('{} is not a valid configuration key'.format(key))
                logger.debug('{} is not a valid configuration key'.format(key))
                continue
            expected_type = self.types.get(key)
            if cast_types:
                try:
                    if expected_type == bool:
                        value = distutils.util.strtobool(value)
                    value = expected_type(value)
                except ValueError:
                    pass
            if not isinstance(value, expected_type):
                raise TypeError(
                    'Got {value} for {key}, expected {expected_type}'
                    .format(
                        value=repr(value),
                        key=key,
                        expected_type=expected_type,
                    )
                )
            normalized_mapping[key] = value
        self.data.extendleft([normalized_mapping])

    @contextmanager
    def override(self, *args, **kwargs):
        self.extend(*args, **kwargs)
        yield self
        self.data.popleft()

    def get(self, key, default=marker):
        if not self.ready:
            raise RuntimeError('Config not loaded')
        for layer in self.data:
            try:
                return layer[key]
            except KeyError:
                continue
        if default is marker:
            raise KeyError(key)
        return default

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        return self.extend({key: value})

    def __getattr__(self, key):
        try:
            return self.get(key)
        except KeyError:
            raise AttributeError

    def as_dict(self):
        d = {}
        for key in self.types:
            if key not in self.sensitive:
                try:
                    d[key] = self.get(key)
                except KeyError:
                    pass
        return d

    def register(self, key, type_, synonyms=None, sensitive=False):
        if synonyms is None:
            synonyms = set()
        if key in self.types:
            raise KeyError('Config key {} is already registered'.format(key))
        if type_ not in self.SUPPORTED_TYPES:
            raise TypeError(
                '{type} is not a supported type'.format(
                    type=type_
                )
            )
        self.types[key] = type_
        for synonym in synonyms:
            self.synonyms[synonym] = key

        if sensitive:
            self.sensitive.add(key)

    def load_from_file(self, filename):
        parser = configparser.SafeConfigParser()
        parser.read(filename)
        data = {}
        for section in parser.sections():
            data.update(dict(parser.items(section)))
        self.extend(data, cast_types=True, strict=True)

    def write(self, filter_sensitive=False):
        parser = configparser.SafeConfigParser()
        parser.add_section('Parameters')
        for layer in reversed(self.data):
            for k, v in layer.items():
                if (filter_sensitive and k in self.sensitive or
                        [s for s in SENSITIVE_KEY_NAMES if s in k]):
                    continue
                parser.set('Parameters', k, str(v))

        with open(LOCAL_CONFIG, 'w') as fp:
            parser.write(fp)

    def load_from_environment(self):
        self.extend(os.environ, cast_types=True)

    def load(self):
        # Apply extra parameters before loading the configs
        self.register_extra_parameters()

        globalConfigName = ".dallingerconfig"
        globalConfig = os.path.expanduser(os.path.join("~/", globalConfigName))
        localConfig = os.path.join(os.getcwd(), LOCAL_CONFIG)

        defaults_folder = os.path.join(os.path.dirname(__file__), "default_configs")
        local_defaults_file = os.path.join(defaults_folder, "local_config_defaults.txt")
        global_defaults_file = os.path.join(defaults_folder, "global_config_defaults.txt")

        # Load the configuration, with local parameters overriding global ones.
        for config_file in [
            global_defaults_file,
            local_defaults_file,
            globalConfig,
        ]:
            self.load_from_file(config_file)

        if os.path.exists(localConfig):
            self.load_from_file(localConfig)

        self.load_from_environment()
        self.ready = True

    def register_extra_parameters(self):
        initialize_experiment_package(os.getcwd())
        extra_parameters = None
        try:
            from dallinger_experiment.experiment import extra_parameters
        except ImportError:
            try:
                from dallinger_experiment.dallinger_experiment import extra_parameters
            except ImportError:
                try:
                    from dallinger_experiment import extra_parameters
                except ImportError:
                    pass
        if extra_parameters is not None and getattr(extra_parameters, 'loaded', None) is None:
            extra_parameters()
            extra_parameters.loaded = True


config = None


def get_config():
    global config

    if config is None:
        config = Configuration()
        for registration in default_keys:
            config.register(*registration)

    return config


def initialize_experiment_package(path):
    """Make the specified directory importable as the `dallinger_experiment` package."""
    # Create __init__.py if it doesn't exist (needed for Python 2)
    init_py = os.path.join(path, '__init__.py')
    if not os.path.exists(init_py):
        open(init_py, 'a').close()

    # Retain already set experiment module
    if sys.modules.get('dallinger_experiment') is not None:
        return

    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    sys.path.insert(0, dirname)
    package = __import__(basename)

    sys.modules['dallinger_experiment'] = package
    package.__package__ = 'dallinger_experiment'
    sys.path.pop(0)
