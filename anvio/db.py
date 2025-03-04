# -*- coding: utf-8
# pylint: disable=line-too-long
"""
    Low-level db operations.
"""

import os
import time
import math
import numpy
import pandas as pd
import sqlite3
import warnings

import anvio
import anvio.tables as tables
import anvio.terminal as terminal
import anvio.filesnpaths as filesnpaths

from anvio.errors import ConfigError

__author__ = "Developers of anvi'o (see AUTHORS.txt)"
__copyright__ = "Copyleft 2015-2018, the Meren Lab (http://merenlab.org/)"
__credits__ = []
__license__ = "GPL 3.0"
__version__ = anvio.__version__
__maintainer__ = "A. Murat Eren"
__email__ = "a.murat.eren@gmail.com"
__status__ = "Development"


# Converts numpy numbers into storable python types that sqlite3 is expecting
sqlite3.register_adapter(numpy.int64, int)
sqlite3.register_adapter(numpy.float64, float)
warnings.simplefilter(action='ignore', category=FutureWarning)


def get_list_in_chunks(input_list, num_items_in_each_chunk=5000):
    """Yield smaller bits of a list"""

    for index in range(0, len(input_list), num_items_in_each_chunk):
        yield input_list[index:index + num_items_in_each_chunk]


class DB:
    def __init__(self, db_path, client_version, new_database=False, ignore_version=False, read_only=False, skip_rowid_prepend=False,
                 run=terminal.Run(), progress=terminal.Progress()):
        self.db_path = db_path
        self.read_only = read_only
        self.version = None

        self.run = run
        self.progress = progress

        # these anonymous functions report whether the ROWID will be added
        # to its rows read from the database or not. if the first column of a given
        # table does not contain unique variables, anvi'o prepends the ROWID of each
        # column to index 0, unless `skip_rowid_prepend` is True
        self.ROWID_PREPENDS_ROW_DATA = lambda table_name: False if skip_rowid_prepend else tables.requires_unique_entry_id[table_name]
        self.PROPER_SELECT_STATEMENT = lambda table_name: 'ROWID as "entry_id", *' if self.ROWID_PREPENDS_ROW_DATA(table_name) else '*'

        if new_database:
            filesnpaths.is_output_file_writable(db_path)
        else:
            filesnpaths.is_file_exists(db_path)

        if new_database and os.path.exists(self.db_path):
            os.remove(self.db_path)

        if self.read_only and new_database:
            raise ConfigError("One cannot create a new database that is read-only.")

        if not self.read_only:
            self.check_if_db_writable()

        try:
            self.conn = sqlite3.connect(self.db_path)
        except Exception as e:
            raise ConfigError(f"This one time someone was not happy with '{self.db_path}' and '{e}', they said.")

        self.conn.text_factory = str

        self.cursor = self.conn.cursor()

        self.table_names_in_db = self.get_table_names()

        self.db_connected = True

        if new_database:
            self.create_self()
            self.set_version(client_version)
        else:
            self.version = self.get_version()
            if str(self.version) != str(client_version) and not ignore_version:
                if int(self.version) > int(client_version):
                    progress.reset()
                    raise ConfigError("Bad news of the day: the database at %s was generated with an anvi'o version that is 'newer' than "
                                      "the one you are actively using right now. We know, you hate to hear this, but you need to upgrade "
                                      "your anvi'o :(" % self.db_path)
                else:
                    progress.reset()
                    raise ConfigError(f"The database at '{self.db_path}' is outdated (this database is v{self.version} and your anvi'o installation "
                                      f"wants to work with v{client_version}). You can migrate your database without losing any data using the "
                                      f"program `anvi-migrate` with either of the flags `--migrate-dbs-safely` or `--migrate-dbs-quickly`.")

            bad_tables = [table_name for table_name in self.table_names_in_db if table_name not in tables.requires_unique_entry_id]
            if len(bad_tables):
                raise ConfigError("You better be a programmer tinkering with anvi'o databases adding new tables or something. Otherwise we "
                                  "have quite a serious problem :/ Each table in a given anvi'o database must have an entry in the "
                                  "anvio/tables/__init__.py dictionary `requires_unique_entry_id` to explicitly define whether anvi'o "
                                  "should add a unique entry id for its contents upon retrieval as a dictionary. The following tables "
                                  "in this database do not satisfy that: '%s'. You can solve this problem by adding an entry into that "
                                  "dictionary." % (', '.join(bad_tables)))


    def __enter__(self):
        return self


    def __exit__(self, *args):
        self.disconnect()


    def _not_if_read_only(func):
        def inner(self, *args, **kwargs):
            if self.read_only:
                raise ConfigError(f"Cannot call `DB.{func.__name__}` in read-only instance")
            else:
                return func(self, *args, **kwargs)
        return inner


    def get_version(self):
        try:
            return self.get_meta_value('version')
        except:
            raise ConfigError("%s does not seem to be a database generated by anvi'o :/" % self.db_path)


    def check_if_db_writable(self):
        check_counter = 0
        check_interval = 1 # in seconds
        check_limit = 300 # 5 minutes, in seconds

        journal_path = self.db_path + '-journal'

        while(check_counter < check_limit and filesnpaths.is_file_exists(journal_path, dont_raise=True)):
            if check_counter == 0:
                # print only once
                self.run.info_single("It seems the database at '%s' currently used by another proccess "
                              "for writing operations. Anvi'o refuses to work with this database to avoid corrupting it. "
                              "If you think this is a mistake, you may stop this process and delete the lock file at '%s' after making sure "
                              "no other active process using it for writing. In case this program is ran by automatic workflow manager like snakemake "
                              "Anvi'o will periodically check if the journal file still exists for total of %d minutes. If database is still not writable "
                              "after that time, Anvi'o will stop running. " % (os.path.abspath(self.db_path), os.path.abspath(journal_path), int(check_limit/60)))

            time.sleep(check_interval)
            check_counter += check_interval

        if not check_counter < check_limit:
            raise ConfigError("Database is not writable.")


    @_not_if_read_only
    def create_self(self):
        self._exec('''CREATE TABLE self (key text, value text)''')


    @_not_if_read_only
    def drop_table(self, table_name):
        """Delete a table in the database if it exists"""
        self._exec('''DROP TABLE IF EXISTS %s;''' % table_name)


    @_not_if_read_only
    def create_table(self, table_name, fields, types):
        if len(fields) != len(types):
            raise ConfigError("create_table: The number of fields and types has to match.")

        db_fields = ', '.join(['%s %s' % (t[0], t[1]) for t in zip(fields, types)])
        self._exec('''CREATE TABLE %s (%s)''' % (table_name, db_fields))
        self.commit()
        self.table_names_in_db = self.get_table_names()


    @_not_if_read_only
    def set_version(self, version):
        self.set_meta_value('version', version)
        self.commit()


    @_not_if_read_only
    def set_meta_value(self, key, value):
        self.remove_meta_key_value_pair(key)
        self._exec('''INSERT INTO self VALUES(?,?)''', (key, value,))
        self.commit()


    @_not_if_read_only
    def remove_meta_key_value_pair(self, key):
        self._exec('''DELETE FROM self WHERE key="%s"''' % key)
        self.commit()


    @_not_if_read_only
    def update_meta_value(self, key, value):
        self.remove_meta_key_value_pair(key)
        self.set_meta_value(key, value)


    @_not_if_read_only
    def copy_paste(self, table_name, source_db_path, append=False):
        """Copy `table_name` data from another database (`source_db_path`) into yourself

        Arguments
        =========
        append : bool, False
            If True, the table is appened to the source DB, rather than replaced.
        """

        source_db = DB(source_db_path, None, ignore_version=True)
        num_entries_in_source = source_db.get_row_counts_from_table(table_name)

        if not num_entries_in_source:
            return

        # we are done with the source DB python object. The rest we do in SQL
        # for huge performance gains
        source_db.disconnect()

        if not append:
            self._exec('''DELETE FROM %s''' % table_name)

        self._exec('''ATTACH "%s" AS source_db''' % source_db_path)
        self._exec('''INSERT INTO main.%s SELECT * FROM source_db.%s''' % (table_name, table_name))
        self._exec('''DETACH DATABASE "source_db"''')


    def get_max_value_in_column(self, table_name, column_name, value_if_empty=None, return_min_instead=False):
        """Get the maximum OR minimum column value in a table

        Parameters
        ==========
        value_if_empty : object, None
            If not None and table has no entries, value returned is value_if_empty.
        """

        response = self._exec("""SELECT %s(%s) FROM %s""" % ('MIN' if return_min_instead else 'MAX', column_name, table_name))
        rows = response.fetchall()

        val = rows[0][0]

        if isinstance(val, type(None)):
            return value_if_empty

        try:
            val = int(val)
        except ValueError:
            pass

        return val


    def get_meta_value(self, key, try_as_type_int=True, return_none_if_not_in_table=False):
        """if try_as_type_int, value is attempted to be converted to integer. If it fails, no harm no foul."""

        response = self._exec("""SELECT value FROM self WHERE key='%s'""" % key)
        rows = response.fetchall()
        if not rows and return_none_if_not_in_table:
            return None
        if not rows:
            raise ConfigError("A value for '%s' does not seem to be set in table 'self'." % key)

        val = rows[0][0]

        if isinstance(val, type(None)):
            return None

        if try_as_type_int:
            try:
                val = int(val)
            except ValueError:
                pass

        return val


    def commit(self):
        self.conn.commit()


    def disconnect(self):
        if self.db_connected:
            self.conn.commit()
            self.conn.close()
            self.db_connected = False
        else:
            # it is already disconnected
            pass


    def _exec(self, sql_query, value=None):
        """Execute an arbitrary sql statement

        Notes
        =====
        - This is a private method, and so it is presumed whoever uses it knows what they are doing.
          For this reason, it is not decorated with _not_if_read_only. It is therefore possible to write
          to the DB using this method, even with self.read_only = True
        """

        if value:
            ret_val = self.cursor.execute(sql_query, value)
        else:
            ret_val = self.cursor.execute(sql_query)

        self.commit()
        return ret_val


    def _exec_many(self, sql_query, values):
        """Execute many sql statements

        Notes
        =====
        - This is a private method, and so it is presumed whoever uses it knows what they are doing.
          For this reason, it is not decorated with _not_if_read_only. It is therefore possible to write
          to the DB using this method, even with self.read_only = True
        """

        chunk_counter = 0
        for chunk in get_list_in_chunks(values):
            if anvio.DEBUG:
                self.progress.reset()
                self.run.info_single("Adding the chunk %d with %d entries of %d total is being added to the db with "
                                     "the SQL command '%s'." \
                                    % (chunk_counter, len(chunk), len(values), sql_query), nl_before=1)

            self.cursor.executemany(sql_query, chunk)

            chunk_counter += 1

        return True


    @_not_if_read_only
    def insert(self, table_name, values=()):
        query = '''INSERT INTO %s VALUES (%s)''' % (table_name, ','.join(['?'] * len(values)))
        return self._exec(query, values)


    @_not_if_read_only
    def insert_many(self, table_name, entries=None):
        if len(entries):
            query = '''INSERT INTO %s VALUES (%s)''' % (table_name, ','.join(['?'] * len(entries[0])))
            return self._exec_many(query, entries)


    @_not_if_read_only
    def insert_rows_from_dataframe(self, table_name, dataframe, raise_if_no_columns=True):
        """Insert rows from a dataframe

        Parameters
        ==========
        raise_if_no_columns : bool, True
            If True, if dataframe has no columns (e.g. dataframe = pd.DataFrame({})), this function
            returns without raising error.

        Notes
        =====
        - This should one day be replaced with the following code:
            if 'entry_id' in structure:
                # This table has an entry_id of, we have to be aware of it
                if 'entry_id' in df.columns:
                    # The user already has an 'entry_id' column. We assume they know what they are doing
                    next_available_id = df['entry_id'].max() + 1
                else:
                    num_entries = df.shape[0]
                    next_available_id = self.get_max_value_in_column(name, 'entry_id', value_if_empty=-1) + 1
                    df['entry_id'] = range(next_available_id, next_available_id + num_entries)
                    next_available_id += num_entries
            else:
                next_available_id = None

            # subset columns and reorder according to the table structure
            df = df[structure]

            dtypes = dict(zip(structure, types))

            df.to_sql(
                name,
                self.conn,
                if_exists='append',
                chunksize=chunksize,
                dtype=dtypes,
                index=False
            )

            return next_available_id
        """

        self.is_table_exists(table_name)

        if not list(dataframe.columns) and not raise_if_no_columns:
            # if the dataframe has no colums, we just return
            return

        if len(set(dataframe.columns)) != len(list(dataframe.columns)):
            raise ConfigError("insert_rows_from_dataframe :: There is at least one duplicate column "
                              "name in the dataframe. Here is the list of columns: [{}].".\
                               format(", ".join(list(dataframe.columns))))

        if set(dataframe.columns) != set(self.get_table_structure(table_name)):
            raise ConfigError("insert_rows_from_dataframe :: The columns in the dataframe "
                              "do not equal the columns of the requested table. "
                              "The columns from each are respectively ({}); and ({}).".\
                               format(", ".join(list(dataframe.columns)),
                                      ", ".join(self.get_table_structure(table_name))))

        # conform to the column order of the table structure
        dataframe = dataframe[self.get_table_structure(table_name)]

        entries = [tuple(row) for row in dataframe.values]
        self.insert_many(table_name, entries=entries)


    def is_table_exists(self, table_name):
        if table_name not in self.table_names_in_db:
            raise ConfigError(f"The database at {self.db_path} does not seem to have a table named `{table_name}` :/ "
                              f"Here is a list of table names this database knows: {', '.join(self.table_names_in_db)}")


    def get_all_rows_from_table(self, table_name):
        self.is_table_exists(table_name)

        response = self._exec('''SELECT %s FROM %s''' % (self.PROPER_SELECT_STATEMENT(table_name), table_name))
        return response.fetchall()


    def get_some_rows_from_table(self, table_name, where_clause):
        self.is_table_exists(table_name)

        where_clause = where_clause.replace('"', "'")

        response = self._exec('''SELECT %s FROM %s WHERE %s''' % (self.PROPER_SELECT_STATEMENT(table_name), table_name, where_clause))
        return response.fetchall()


    def get_row_counts_from_table(self, table_name, where_clause=None):
        self.is_table_exists(table_name)

        if where_clause:
            where_clause = where_clause.replace('"', "'")
            response = self._exec('''SELECT COUNT(*) FROM %s WHERE %s''' % (table_name, where_clause))
        else:
            response = self._exec('''SELECT COUNT(*) FROM %s''' % (table_name))

        return response.fetchall()[0][0]


    @_not_if_read_only
    def remove_some_rows_from_table(self, table_name, where_clause):
        self.is_table_exists(table_name)

        where_clause = where_clause.replace('"', "'")

        self._exec('''DELETE FROM %s WHERE %s''' % (table_name, where_clause))
        self.commit()


    def get_single_column_from_table(self, table, column, unique=False, where_clause=None):
        self.is_table_exists(table)

        if where_clause:
            where_clause = where_clause.replace('"', "'")
            response = self._exec('''SELECT %s %s FROM %s WHERE %s''' % ('DISTINCT' if unique else '', column, table, where_clause))
        else:
            response = self._exec('''SELECT %s %s FROM %s''' % ('DISTINCT' if unique else '', column, table))
        return [t[0] for t in response.fetchall()]


    def get_some_columns_from_table(self, table, comma_separated_column_names, unique=False, where_clause=None):
        self.is_table_exists(table)

        if where_clause:
            where_clause = where_clause.replace('"', "'")
            response = self._exec('''SELECT %s %s FROM %s WHERE %s''' % ('DISTINCT' if unique else '', comma_separated_column_names, table, where_clause))
        else:
            response = self._exec('''SELECT %s %s FROM %s''' % ('DISTINCT' if unique else '', comma_separated_column_names, table))
        return response.fetchall()


    def get_frequencies_of_values_from_a_column(self, table_name, column_name):
        self.is_table_exists(table_name)

        response = self._exec('''select %s, COUNT(*) from %s group by %s''' % (column_name, table_name, column_name))

        return response.fetchall()


    def get_table_column_types(self, table_name):
        self.is_table_exists(table_name)

        response = self._exec('PRAGMA TABLE_INFO(%s)' % table_name)
        return [t[2] for t in response.fetchall()]


    def get_table_columns_and_types(self, table_name):
        self.is_table_exists(table_name)

        response = self._exec('PRAGMA TABLE_INFO(%s)' % table_name)
        return dict([(t[1], t[2]) for t in response.fetchall()])


    def get_table_structure(self, table_name):
        self.is_table_exists(table_name)

        response = self._exec('''SELECT * FROM %s''' % table_name)
        return [t[0] for t in response.description]


    def get_table_as_list_of_tuples(self, table_name, table_structure=None):
        return self.get_all_rows_from_table(table_name)


    def smart_get(self, table_name, column=None, data=None, string_the_key=False, error_if_no_data=True, progress=None, omit_parent_column=False):
        """A wrapper function for `get_*_table_as_dict` and that is not actually that smart.

        If the user is interested in only some of the data, they can build a where clause
        and use `get_some_rows_from_table_as_dict`. If the user is interested in the entire
        table data, then they would call `get_table_as_dict`. But in situations where it is
        not certain whether there will be a where clause, the if/else statements clutter the
        code. Here is an example:

            ----8<-------8<-------8<-------8<-------8<-------8<-------8<-------8<-------8<-------8<-------8<-------
            def func(items_of_interest=None):
                (...)

                if items_of_interest:
                    where_clause = 'column_name IN (%s)' % (','.join(['"%s"' % item for item in items_of_interest]))
                    d = get_some_rows_from_table_as_dict(table_name, where_clause=where_clause)
                else:
                    d = get_table_as_dict(table_name)

                (...)
            ---->8------->8------->8------->8------->8------->8------->8------->8------->8------->8------->8-------

        This function cleans up this mess as this call is equivalent to the example code above:

            ----8<-------8<-------8<-------8<-------8<-------8<-------8<-------8<-------8<-------8<-------8<-------
            def func(items_of_interest=None):
                (...)

                smart_get(table_name, column_name, items_of_interest)

                (...)
            ---->8------->8------->8------->8------->8------->8------->8------->8------->8------->8------->8-------

        Paremeters
        ==========
        table_name: str
            The anvi'o data table name
        column: str
            The column name that will be used to select from table
        data: set
            A set of item names of interest. If the set is empty, the function will return the entire content of `table_name`
        """

        table_columns_and_types = self.get_table_columns_and_types(table_name)

        if column not in table_columns_and_types:
            raise ConfigError(f"The column name `{column}` is not in table `{table_name}` :/")

        if column and data:
            if table_columns_and_types[column] in ["numeric", "integer"]:
                items = ','.join([str(d) for d in data])
            else:
                items = ','.join(['"%s"' % d for d in data])

            if progress:
                progress.update(f'Reading **SOME** data from `{table_name.replace("_", " ")}` table :)')

            return self.get_some_rows_from_table_as_dict(table_name, where_clause=f"{column} IN ({items})", string_the_key=string_the_key, error_if_no_data=error_if_no_data, omit_parent_column=omit_parent_column)
        else:
            if progress:
                progress.update(f'Reading **ALL** data from `{table_name.replace("_", " ")}` table :(')

            return self.get_table_as_dict(table_name, string_the_key=string_the_key, error_if_no_data=error_if_no_data, omit_parent_column=omit_parent_column)


    def get_table_as_dict(self, table_name, string_the_key=False, columns_of_interest=None, keys_of_interest=None, omit_parent_column=False, error_if_no_data=True, log_norm_numeric_values=False):
        if self.ROWID_PREPENDS_ROW_DATA(table_name):
            table_structure = ['entry_id'] + self.get_table_structure(table_name)
        else:
            table_structure = self.get_table_structure(table_name)

        columns_to_return = list(range(0, len(table_structure)))

        if columns_of_interest and not isinstance(columns_of_interest, type([])):
            raise ConfigError("The parameter `columns_of_interest` must be of type <list>.")

        if omit_parent_column:
            if '__parent__' in table_structure:
                columns_to_return.remove(table_structure.index('__parent__'))
                table_structure.remove('__parent__')

        if columns_of_interest:
            for col in table_structure[1:]:
                if col not in columns_of_interest:
                    columns_to_return.remove(table_structure.index(col))

        if len(columns_to_return) == 1:
            if error_if_no_data:
                raise ConfigError("get_table_as_dict :: after removing an column that was not mentioned in the columns "
                                   "of interest by the client, nothing was left to return...")
            else:
                return {}

        rows = self.get_all_rows_from_table(table_name)

        #-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----8<-----
        #
        # SAD TABLES BEGIN
        #
        # NOTE from the past:
        # FIXME FIXME FIXME FIXME FIXME FIXME FIXME FIXME FIXME FIXME FIXME FIXME
        # this is one of the most critical design mistakes that remain in anvi'o. we set `entry_id` values
        # in table classes depending on the data that will be entered into the database. this is how it goes:
        # anvi'o learns the highest entry id in a table (to which it is about to enter some data), for each db
        # entry assigns a new `entry_id`, enters the data. it is all good when there is a single process doing it.
        # but when there are multiple processes running in parallel, sometimes race conditions occur: two processes
        # learn the max entry id about the same time, and when they finally enter the data to the db, some entries
        # end up not being unique. this is a toughie because sometimes entry ids are used to connect distinct
        # information from different tables, so they must be known before the data goes into the database, etc.
        # when these race conditions occur, anvi'o gives an error telling the user kindly that they are fucked. but in
        # some cases it is possible to recover from that (THE CODE BELOW TRIES TO DO THAT) by reassigning all ids on the
        # fly to the resulting data dictionary (i.e., not paying atention to entry ids in the database and basically using
        # new ones to avoid key information to not be overwritten due to the lack of unique entry ids which become keys for
        # the data dictionary). in other cases there are no ways to fix it, such as for HMM tables.. The ACTUAL SOLUTION to\
        # this is to remove `entry_id` columns from every table in anvi'o, and using SQLite indexes as entry ids.
        #
        # NOTE from the future
        # Every SQLite table has an implicit column called ROWID. Does this solve our problem?
        #
        # NOTE from a more recent future: we no longer have the entry_id problem for most tables .. except
        # the hmm_hits table. the reason it has to be there is because we need to know the precise entry ids for
        # hmm hits to be able to track them in splits. there probably are better ways to do that. So here I am leaving
        # a FIXME. once this is resolved, the entry_id routines in Table base class can be deleted safely. until then,
        # we will suffer from race conditions occasionally, and this embarrassment will stay here in the code..
        if table_name == tables.hmm_hits_table_name:
            unique_keys = set([r[0] for r in rows])
            if len(unique_keys) != len(rows):
                if anvio.FIX_SAD_TABLES:
                    if 'hmm' in table_name:
                        raise ConfigError("You asked anvi'o to fix sad tables, but the sad table you're trying to fix happens to "
                                          "be related to HMM operations in anvi'o, where supposedly unique entries tie together "
                                          "multiple tables. Long story short, solving this while ensuring everything is done right "
                                          "is quite difficult and there is no reason to take any risks. The best you can do is to "
                                          "remove all HMMs from your contigs database, and re-run them with a single instance of "
                                          "`anvi-run-hmms` command (you can use multiple threads, but you shouldn't send multiple "
                                          "`anvi-run-hmms` to your cluster to be run on the same contigs database in parallel -- "
                                          "that's what led you to this point at the first place). Apologies for this bioinformatics "
                                          "poo poo :( It is all on us.")

                    self.run.info_single("You have sad tables. You have used `--fix-sad-tables` flag. Now anvi'o will try to fix them...", mc="red")

                    # here we will update the rows data with a small memory fingerprint:
                    entry_id_counter = 0
                    for i in range(0, len(rows)):
                        row = rows[i]
                        rows[i] = [entry_id_counter] + list(row[1:])
                        entry_id_counter += 1

                    # now we will remove the previous table, and enter the new data with up-to-date entry ids
                    table_structure = self.get_table_structure(table_name)

                    # delete the table content *gulp*
                    self._exec('''DELETE FROM %s''' % table_name)

                    # enter corrected data
                    self._exec_many('''INSERT INTO %s VALUES (%s)''' % (table_name, ','.join(['?'] * len(table_structure))), rows)

                    self.run.info_single("If you are seeing this line, it means anvi'o managed to fix those sad tables. No more sad! "
                                    "But please make double sure that nothing looks funny in your results. If you start getting "
                                    "errors and you wish to contact us for that, please don't forget to mention that you did try "
                                    "to fix your sad tables.", mc="green")
                else:
                    raise ConfigError(f"This is one of the core functions of anvi'o you never want to hear from, but there seems "
                                      f"to be something wrong with the table {table_name} (in the database at '{self.db_path}') "
                                      f"that you are trying to read from. While there are {len(rows)} items in this table, there "
                                      f"are only {len(unique_keys)} unique keys, which means some of them are going to be overwritten "
                                      f"when this function creates a final dictionary of data to return. This only happens when the "
                                      f"user (or their fancy workflow) runs multiple instances of `anvi-run-hmms` on the same "
                                      f"contigs database with different HMM profiles. Anvi'o is very sad for not handling this "
                                      f"properly, but such database tables need fixin' before things can continue :( If you would "
                                      f"like anvi'o to try to fix this, please run the same command you just run with the flag "
                                      f"`--fix-sad-tables`. If you do that it is a great idea to backup your original database "
                                      f"and then very carefully check the results to make sure things do not look funny. If you want "
                                      f"things to go parallel and fast, please consider using the anvi'o snakemake workflows.")

        #
        # SAD TABLES END
        #
        #----->8----->8----->8----->8----->8----->8----->8----->8----->8----->8----->8----->8----->8----->8----->8-----


        results_dict = {}

        if keys_of_interest:
            keys_of_interest = set(keys_of_interest)

        for row in rows:
            entry = {}

            if keys_of_interest:
                if row[0] in keys_of_interest:
                    # so we are interested in keeping this, reduce the size of the
                    # hash size to improve the next inquiry, and keep going.
                    keys_of_interest.remove(row[0])
                else:
                    # we are not intersted in this one, continue:
                    continue

            for i in columns_to_return[1:]:
                value = row[i]
                if log_norm_numeric_values:
                    if type(value) == float or type(value) == int:
                        entry[table_structure[i]] = math.log10(value + 1)
                else:
                    entry[table_structure[i]] = value

            if string_the_key:
                results_dict[str(row[0])] = entry
            else:
                results_dict[row[0]] = entry

        return results_dict


    def get_table_as_dataframe(self, table_name, where_clause=None, columns_of_interest=None, drop_if_null=False, error_if_no_data=True):
        """Get the table as a pandas DataFrame object

        Parameters
        ==========
        table_name : str

        where_clause : str, None
            SQL WHERE clause. If None, everything is fetched.

        columns_of_interest : list, None
            Which columns do you want to return? If None, all are returned. Applied after where_clause.

        drop_if_null : bool, False
            Drop columns if they contain all NULL values, i.e. np.nan, or ''

        error_if_no_data : bool, True
            Raise an error if the dataframe has 0 rows. Checked after where_clause.
        """

        if self.ROWID_PREPENDS_ROW_DATA(table_name):
            table_structure = ['entry_id'] + self.get_table_structure(table_name)
        else:
            table_structure = self.get_table_structure(table_name)

        if columns_of_interest:
            columns_of_interest = list(columns_of_interest)
        else:
            columns_of_interest = table_structure

        if where_clause:
            where_clause = where_clause.replace('"', "'")
            results_df = pd.read_sql('''SELECT %s FROM "%s" WHERE %s''' % (self.PROPER_SELECT_STATEMENT(table_name), table_name, where_clause), self.conn, columns=table_structure)
        else:
            results_df = pd.read_sql('''SELECT %s FROM "%s"''' % (self.PROPER_SELECT_STATEMENT(table_name), table_name), self.conn, columns=table_structure)

        if results_df.empty and error_if_no_data:
            raise ConfigError("DB.get_table_as_dataframe :: The dataframe requested is empty")

        if drop_if_null:
            for col in columns_of_interest.copy():
                if results_df[col].isna().all():
                    # Column contains only entries that equate to pandas NA
                    columns_of_interest.remove(col)

                elif (results_df[col] == '').all():
                    # Column contains all empty strings
                    columns_of_interest.remove(col)

        return results_df[columns_of_interest]


    def get_some_rows_from_table_as_dict(self, table_name, where_clause, error_if_no_data=True, string_the_key=False, row_num_as_key=False, omit_parent_column=False):
        """This is similar to get_table_as_dict, but much less general.

        get_table_as_dict can do a lot, but it first reads all data into the memory to operate on it.
        In some cases the programmer may like to access to only a small fraction of entries in a table
        by using `WHERE column = value` notation, which is not possible with the more generalized
        function.

        Parameters
        ==========
        table_name: str
             which table to get rows from
        where_clause: str
             SQL-style where clause for row selection
        error_if_no_data: bool
             if true, this function will raise an error if no data is selected from the table. otherwise, it will
             quietly return the empty dictionary
        string_the_key: bool
             if true, the row number will be converted to a string before being used as a key in the dictionary
        row_num_as_key: bool
             added as parameter so this function works for KEGG MODULES.db, which does not have unique IDs in the
             first column. If True, the returned dictionary will be keyed by integers from 0 to (# rows returned - 1)
        omit_parent_column: bool
             removes __parent__ column from the data to be returned if __parent__ exists in table structure.

        Returns
        =======
        results_dict: dictionary
             contains the requested rows from the table
        """

        results_dict = {}

        where_clause = where_clause.replace('"', "'")

        if self.ROWID_PREPENDS_ROW_DATA(table_name):
            table_structure = ['entry_id'] + self.get_table_structure(table_name)
        else:
            table_structure = self.get_table_structure(table_name)

        if omit_parent_column and '__parent__' in table_structure:
            table_structure.remove('__parent__')

        columns_to_return = list(range(0, len(table_structure)))

        rows = self.get_some_rows_from_table(table_name, where_clause)

        row_num = 0
        for row in rows:
            entry = {}

            if row_num_as_key:
                entry[table_structure[0]] = row[0]
                for i in columns_to_return[1:]:
                    entry[table_structure[i]] = row[i]

                if string_the_key:
                    results_dict[str(row_num)] = entry
                else:
                    results_dict[row_num] = entry
            else:
                for i in columns_to_return[1:]:
                    entry[table_structure[i]] = row[i]

                if string_the_key:
                    results_dict[str(row[0])] = entry
                else:
                    results_dict[row[0]] = entry

            row_num += 1

        if error_if_no_data and not len(results_dict):
            raise ConfigError("Query on %s with the where clause of '%s' did not return anything." % (table_name, where_clause))

        return results_dict


    def get_table_names(self):
        response = self._exec("""select name from sqlite_master where type='table'""")
        return [r[0] for r in response.fetchall()]
