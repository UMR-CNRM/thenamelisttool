"""
A bunch of classes and functions that deal with TNT configuration files and
directives.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import io
import os
import string
import sys

import six

from bronx.compat.moves import collections_abc
from bronx.fancies import loggers
from bronx.syntax.decorators import secure_getattr
from .namadapter import BronxNamelistAdapter

tntlog = loggers.getLogger('tntlog')

# Detect TNT's configuration files directory
TPL_DIRECTORY = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                             'templates')


# EXCEPTIONS
#

class TntDirectiveError(Exception):
    """Any exception raised by a TNT configuration class should derive form this one."""
    pass


class TntDirectiveUnkownError(TntDirectiveError):
    """The TNT directive is unknown."""

    def __init__(self, name):
        errmsg = 'The "{:s}" directive is not allowed with TNT.'.format(name)
        super(TntDirectiveUnkownError, self).__init__(errmsg)


class TntDirectiveValueError(TntDirectiveError):
    """An inappropriate value was given as a TNT directive."""

    def __init__(self, name, value):
        errmsg = '"{!s}" is not an appropriate value for the "{:s}" directive.'.format(value, name)
        super(TntDirectiveValueError, self).__init__(errmsg)


class TntStackDirectiveError(TntDirectiveError):
    """Syntax error in the TNT stack directive file."""
    pass


# TNT directives part
#

class TntDirective(object):
    """Class that holds all the necessary informations about TNT directives.

    It is in charge of checking the correctness of all the provided attributes.
    """

    _ALLOWED_DIRECTIVES = set(('keys_to_remove', 'keys_to_set', 'keys_to_move',
                               'blocks_to_move', 'blocks_to_remove', 'new_blocks',
                               'macros', 'namdelta'))

    def _check_keytuple(self, val, theexc, unique=False):
        """Verify if *val* is some kind of a (block, key) tuple description."""
        keylist = list()
        # Reformat dictionaries, iterables, ...
        if isinstance(val, collections_abc.Mapping):
            for b, v in val.items():
                if isinstance(v, collections_abc.Iterable) and not isinstance(v, six.string_types):
                    keylist.extend([(b, kk) for kk in v])
                else:
                    keylist.append((b, v), )
        elif isinstance(val, collections_abc.Iterable):
            if all([isinstance(v, collections_abc.Iterable) and not isinstance(v, six.string_types)
                    for v in val]):
                keylist.extend(val)
            else:
                keylist.append(tuple(val))
        else:
            raise theexc
        # Final check...
        if not all([len(k) == 2 and
                    isinstance(k[0], six.string_types) and
                    isinstance(k[1], six.string_types)
                    for k in keylist]):
            raise theexc
        # Unique element wanted ?
        if unique:
            if len(keylist) > 1:
                raise theexc
            return keylist[0]
        else:
            return set(keylist)

    def _process_keys_to_remove(self, val):
        myexc = TntDirectiveValueError('keys_to_remove', val)
        return self._check_keytuple(val, myexc)

    def _process_keys_to_set(self, val, theexc=None):
        kdict = dict()
        myexc = theexc or TntDirectiveValueError('keys_to_set', val)
        if isinstance(val, collections_abc.Mapping):
            for k, v in val.items():
                if isinstance(v, collections_abc.Mapping):
                    for kk, vv in v.items():
                        kdict[self._check_keytuple((k, kk), myexc, unique=True)] = vv
                elif isinstance(k, collections_abc.Iterable):
                    kdict[self._check_keytuple(k, myexc, unique=True)] = v
                else:
                    raise myexc
        else:
            raise myexc
        return kdict

    def _process_keys_to_move(self, val):
        kdict = dict()
        myexc = TntDirectiveValueError('keys_to_move', val)
        keystructure = self._process_keys_to_set(val, theexc=myexc)
        for k, v in keystructure.items():
            kdict[k] = self._check_keytuple(v, myexc, unique=True)
        return kdict

    def _process_blocks_to_move(self, val):
        if not (isinstance(val, collections_abc.Mapping) and
                all([isinstance(k, six.string_types) and isinstance(v, six.string_types)
                     for k, v in val.items()])):
            raise TntDirectiveValueError('blocks_to_move', val)
        return {k: v for k, v in val.items()}

    def _process_set_of_blocks(self, val, realname):
        if (isinstance(val, collections_abc.Iterable) and
                not isinstance(val, six.string_types) and
                all([isinstance(v, six.string_types) for v in val])):
            return set(val)
        elif isinstance(val, six.string_types):
            return set([val, ])
        else:
            raise TntDirectiveValueError(realname, val)

    def _process_blocks_to_remove(self, val):
        return self._process_set_of_blocks(val, 'blocks_to_remove')

    def _process_new_blocks(self, val):
        return self._process_set_of_blocks(val, 'new_blocks')

    def _process_macros(self, val):
        if not (isinstance(val, collections_abc.Mapping) and
                all([isinstance(k, six.string_types) for k in val.keys()])):
            raise TntDirectiveValueError('macros', val)
        return {k: v for k, v in val.items()}

    def _process_namdelta(self, val):
        if not (isinstance(val, six.string_types)):
            raise TntDirectiveValueError('namdelta', val)
        return val

    def __init__(self, **kwargs):
        self._internals = dict()
        # Is the directive allowed ?
        for k, v in kwargs.items():
            if k not in self._ALLOWED_DIRECTIVES:
                raise TntDirectiveUnkownError(k)
            self._internals[k] = getattr(self, '_process_{:s}'.format(k))(v)

    @secure_getattr
    def __getattr__(self, item):
        if item not in self._ALLOWED_DIRECTIVES:
            raise TntDirectiveUnkownError(item)
        else:
            return self._internals.get(item, None)


def read_directives(filename):
    """
    Read TNT directives in an external file (**filename**).

    For a template of directives, call function *write_directives_template()*.
    """
    if os.path.splitext(filename)[1] in ('.yaml', '.yml'):
        import yaml
        with io.open(filename, 'r') as yamlfh:
            return TntDirective(**yaml.load(yamlfh, Loader=yaml.SafeLoader))
    else:
        prev_bytecode_flag = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            if sys.version_info.major == 3 and sys.version_info.minor >= 4:
                import importlib.util as imputil  # @UnresolvedImport
                spec = imputil.spec_from_file_location(os.path.basename(filename),
                                                       os.path.abspath(filename))
                m = imputil.module_from_spec(spec)
                spec.loader.exec_module(m)
            else:
                import imp  # @UnresolvedImport
                m = imp.load_source(filename, os.path.abspath(filename))
        finally:
            sys.dont_write_bytecode = prev_bytecode_flag
        return TntDirective(**{k: v for k, v in m.__dict__.items() if not k.startswith('_')})


# TNTstack directives part
#

class TntStackDirective(object):
    """Class that holds all the necessary informations about TNTstack directives.

    :param str basedir: The name of the directory where the TNTstack reqests lies
    :param list[dict] todolist: The list of actions to be performed
    :param dict[dict] directives: A list of TNT directives
    """

    def __init__(self, basedir, todolist, directives=None):
        self._basedir = basedir
        self._directives = dict()
        self._todolist = list()
        self._directives_init(directives or dict())
        self._todolist_init(todolist)

    def _directives_init(self, directives):
        """
        Read the *directives* attribute and create :class:`TntDirective` objects
        from that.
        """
        if not (isinstance(directives, collections_abc.Mapping) and
                all([isinstance(v, collections_abc.Mapping) for v in directives.values()])):
            raise TntStackDirectiveError('The directives argument must be a mapping of mappings')
        for k, v in directives.items():
            if 'external' in v:
                newdir = read_directives(os.path.join(self._basedir, v['external']))
            else:
                newdir = TntDirective(**v)
            self._directives[k] = newdir

    def _checkdict(self, action, values, attr, str_or_list=False):
        """Check that the *values* dictionary has a valid *attr* item.

        :param str action: The name of the current action (used to print meaningful
                           error messages).
        :param bool str_or_list: It *True*, the *attr* item can be either a string
                                 or a list of strings. (otherwise, it has to be a string).
        """
        stuff = values.get(attr, None)
        if stuff is None:
            tntlog.error("Error while processing todo list item:\n%s", values)
            raise TntStackDirectiveError('The "{:s}" entry is mandatory with the "{:s}" action'
                                         .format(attr, action))
        if isinstance(stuff, six.string_types) or not isinstance(stuff, collections_abc.Iterable):
            stuff = [stuff, ]
        else:
            stuff = [v for v in stuff]
        if str_or_list:
            return stuff
        else:
            if len(stuff) != 1:
                tntlog.error("Error while processing todo list item:\n%s", values)
                raise TntStackDirectiveError('The "{:s}" entry requires a unique element ("{:s}" action).'
                                             .format(attr, action))
            return stuff[0]

    def _todolist_init(self, todolist):
        """Read the *todolist* attribute and check that everything is ok."""
        if not (isinstance(todolist, collections_abc.Iterable) and
                all([isinstance(v, collections_abc.Mapping) for v in todolist])):
            raise TntStackDirectiveError('The todolist argument must be an iterable of mappings')
        for todo in todolist:
            action = todo.get('action', None)
            action_d = dict(action=action)

            if action == 'tnt':
                action_d['namelist'] = self._checkdict(action, todo, 'namelist', str_or_list=True)
                action_d['directive'] = self._checkdict(action, todo, 'directive', str_or_list=True)

            elif action == 'create':
                action_d['target'] = self._checkdict(action, todo, 'target')
                if 'external' in todo:
                    action_d['external'] = os.path.join(self._basedir,
                                                        self._checkdict(action, todo, 'external'))
                    if not os.path.isfile(action_d['external']):
                        raise TntStackDirectiveError('The "{:s}"  does not exists.'
                                                     .format(action_d['external']))
                elif 'copy' in todo:
                    action_d['copy'] = self._checkdict(action, todo, 'copy')
                else:
                    action_d['namelist'] = self._checkdict(action, todo, 'namelist')
                    action_d['directive'] = self._checkdict(action, todo, 'directive', str_or_list=True)

            elif action in ('delete', 'touch'):
                action_d['namelist'] = self._checkdict(action, todo, 'namelist', str_or_list=True)

            elif action in ('link', 'move'):
                action_d['target'] = self._checkdict(action, todo, 'target')
                action_d['namelist'] = self._checkdict(action, todo, 'namelist')

            elif action == 'clean_untouched':
                pass

            else:
                raise TntStackDirectiveError('Unknown action "{!s}" requested in the todolist'.format(action))

            # Check the directive entry against existing directives
            if 'directive' in action_d:
                tocheck = ([action_d['directive'], ]
                           if isinstance(action_d['directive'], six.string_types)
                           else action_d['directive'])
                for a_dir in tocheck:
                    if a_dir not in self.directives:
                        raise TntStackDirectiveError('The "{:s}" directive is not defined.'.format(a_dir))
            self._todolist.append(action_d)

    @property
    def directives(self):
        """The dictionary of TNT directives (as :class:`TntDirective` objects)."""
        return self._directives

    @property
    def todolist(self):
        """The todo's list (as a list of dictionaries)."""
        return self._todolist


class TntRecipe(object):
    """
    A YAML Recipe reader, that collects namelists and possibly filter them,
    in sight of finally merging them.
    """

    _include_only = '/+'
    _exclude_only = '/-'

    def __init__(self, recipe_filename, sourcenam_directory=None):
        """
        :param recipe_filename: filepath to the YAML recipe
        :param sourcenam_directory: an optional external directory in which to
            pick the ingredient namelists
        """
        self.sourcenam_directory = sourcenam_directory
        self._load_recipe(recipe_filename)

    def _read_init_final_elements(self, ingredient):
        """Read '__initial__' or '__final__' step **ingredient**."""
        if ingredient is not None:
            if isinstance(ingredient, six.string_types):
                # external namelist
                if self.sourcenam_directory:
                    ingredient = os.path.join(self.sourcenam_directory, ingredient)
                nam = BronxNamelistAdapter(ingredient, macros=self.macros)
            else:
                # internal dict/yaml namelist
                nam = BronxNamelistAdapter(six.StringIO(), macros=self.macros)
                nam.add_blocks(list(ingredient.keys()))
                keys_to_add = {}
                for b in ingredient.keys():
                    if ingredient[b] is not None:
                        for k, v in ingredient[b].items():
                            keys_to_add[(b, k)] = v
                nam.add_keys(keys_to_add)
        else:
            nam = BronxNamelistAdapter(six.StringIO(), macros=self.macros)
        return nam

    def _process_ingredient(self, input_nam, blocks):
        """Preprocess ingredient: read according namelist and filter it."""
        # prepare filtering elements
        _included_blocks = []
        excluded_blocks = []
        included_keys = {}
        excluded_keys = {}
        # read namelist
        input_nam_filename = input_nam.replace(self._exclude_only, '').replace(self._include_only, '')
        if self.sourcenam_directory:
            input_nam_filename = os.path.join(self.sourcenam_directory,
                                              input_nam_filename)
        ingredient = BronxNamelistAdapter(input_nam_filename,
                                          macros=self.macros)
        if blocks != '__all__':
            if True not in [input_nam.endswith(pattern)
                            for pattern in
                            (self._exclude_only, self._include_only)]:
                raise SyntaxError("Namelist name must ends with one of ('{}','{}').".
                                  format(self._exclude_only, self._include_only))
            for b in blocks:
                if isinstance(b, six.string_types):
                    if input_nam.endswith(self._exclude_only):
                        excluded_blocks.append(b)
                    elif input_nam.endswith(self._include_only):
                        _included_blocks.append(b)
                else:
                    if len(b) != 1:
                        raise SyntaxError("?")
                    else:
                        bname = list(b.keys())[0]
                        if bname.endswith(self._include_only):
                            # in this block, include only keys:
                            included_keys[bname.replace(self._include_only, '')] = b[bname]
                        elif bname.endswith(self._exclude_only):
                            # in this block, exclude keys:
                            excluded_keys[bname.replace(self._exclude_only, '')] = b[bname]
                        else:
                            raise SyntaxError("If specifying keys, namelist block must ends with one of ('{}','{}').".
                                              format(self._exclude_only, self._include_only))
            if input_nam.endswith(self._include_only):
                excluded_blocks = [b for b in ingredient
                                   if b not in set(_included_blocks +
                                                   list(included_keys.keys()) +
                                                   list(excluded_keys.keys()))]
        # then filter
        # blocks that are not requested
        ingredient.remove_blocks(excluded_blocks)
        # keys that are excluded
        for b in excluded_keys:
            ingredient.remove_keys([(b, k) for k in excluded_keys[b]])
        # keys that are not requested
        for b in included_keys:
            to_remove = [(b, k) for k in ingredient[b] if k not in included_keys[b]]
            ingredient.remove_keys(to_remove)
        return ingredient

    def _load_recipe(self, recipe_filename):
        """Read YAML file and preprocess ingredients."""
        from bronx.datagrip.misc import load_ordered_yaml
        # load yaml
        recipe = load_ordered_yaml(recipe_filename)
        # specific cases: initialization, finalization, macros
        self.macros = recipe.pop('__macros__', {})
        initial = self._read_init_final_elements(recipe.pop('__initial__', None))
        final = self._read_init_final_elements(recipe.pop('__final__', None))
        self.ingredients = []
        # convert each ingredient into a namelist to be merged
        for input_nam, blocks in recipe.items():
            self.ingredients.append(self._process_ingredient(input_nam, blocks))
        self.ingredients.insert(0, initial)
        self.ingredients.append(final)


# Utility function that deals with template files
#

def get_template(tplname, encoding=None):
    """Retrieve a template file in the dedicated directory."""
    tplfile = os.path.join(TPL_DIRECTORY, tplname)
    with io.open(tplfile, 'r', encoding=encoding) as fhtpl:
        tpl = string.Template(fhtpl.read())
    return tpl


def write_directives_template(out=sys.stdout, tplname='tnt-directive.tpl.py'):
    """Write out a directives template."""
    if isinstance(out, six.string_types):
        outfh = io.open(out, 'w')
    else:
        outfh = out
    outtpl = os.path.join(TPL_DIRECTORY, tplname)
    try:
        with io.open(outtpl, 'r') as tplfh:
            for line in tplfh:
                outfh.write(line)
    finally:
        if isinstance(out, six.string_types):
            outfh.close()
