
using System;
using System.Collections.Immutable;
using System.Timers;
using static System.Net.Mime.MediaTypeNames;

// general explanation:
// 1. the class is built as a readrs - writers solution. we decide how many cells will be locked by each lock as a result
// of the processors number in the cpu. more peocessors means we can handle more locks - means smaller groups.
// 2.  for each cells group we hold 3 objects: readers semaphore, writer semaphore(functions as mutex), readers counter.
// we keep them in arrays - to represents the entire matrix cells's locks. 
// 3. why writers semaphore(1,1) and not mutex - because a mutex lock can't be releases by other thread then the one who locked,
// and here it is necessery (in readers-writers). 
// 4. searchSemaphore: in order to limit the searches occurs in the same time - if requested. 
// 5. mapping the cells to locks - with a mathematical function that gives indexes 0,1,2.... to all the matrix cells and
// then maps them to the correct lock in the locks array (readers/writers) - always maps to index in the array range.
class SharableSpreadSheet
{
    private String[,] matrix;
    private int rows;
    private int cols;
    private Semaphore searchSemaphore;
    private SemaphoreSlim[] chunkWritersMutex;
    private Mutex[] chunkReadersMutex;
    private int[] chunkReadersNum;
    private int locksNum;

    public SharableSpreadSheet(int nRows, int nCols, int nUsers = -1)
    {
        // nUsers used for setConcurrentSearchLimit, -1 mean no limit.
        // construct a nRows*nCols spreadsheet
        this.rows = nRows;
        this.cols = nCols;
        this.matrix = new string[nRows, nCols];
        if (nUsers > 0)
        {
            this.searchSemaphore = new Semaphore(nUsers, nUsers);
        }
        else
        {
            this.searchSemaphore = null;
        }

        // measure the processors num
        this.locksNum = Math.Min(Environment.ProcessorCount * 100, rows * cols);

        this.chunkWritersMutex = new SemaphoreSlim[locksNum];
        this.chunkReadersMutex = new Mutex[locksNum];
        this.chunkReadersNum = new int[locksNum];
        for (int i = 0; i < locksNum; i++)
        {
            this.chunkWritersMutex[i] = new SemaphoreSlim(1, 1);
            this.chunkReadersMutex[i] = new Mutex();
            this.chunkReadersNum[i] = 0;
        }
        for (int i = 0; i < rows; i++)
        {
            for (int j = 0; j < cols; j++)
            {
                // for start
                matrix[i, j] = "";
            }
        }
    }

    // the function that maps each cell to it's correcrt lock. 
    private int get_Lock_index(int row, int col)
    {
        int index_in_matrix_as_array = row * cols + col;
        int mapped_index_in_lock_array = (index_in_matrix_as_array * locksNum) / (rows * cols);
        return mapped_index_in_lock_array;
    }

    // funtions logic from now on : as mentioned - readers-writers:
    // we operate by the readers-writers algorithm.
    // determine if it's a reader function or writer and then locks by readers/writers by that (including counters update -
    // just by the algorithm).
    
    public String getCell(int row, int col)
    {
        // return the string at [row,col]
        if (row < 0 || row >= this.rows || col < 0 || col >= this.cols)
        {
            throw new ArgumentOutOfRangeException("wrong location");
        }

        String s = null;
        int suitable_index = get_Lock_index(row, col);

        try
        {
            chunkReadersMutex[suitable_index].WaitOne();
            chunkReadersNum[suitable_index]++;
            if (chunkReadersNum[suitable_index] == 1)
            {
                chunkWritersMutex[suitable_index].Wait();
            }
        }
        finally
        {
            chunkReadersMutex[suitable_index].ReleaseMutex();
        }


        s = matrix[row, col];

        try
        {
            chunkReadersMutex[suitable_index].WaitOne();
            chunkReadersNum[suitable_index]--;
            if (chunkReadersNum[suitable_index] == 0)
            {
                chunkWritersMutex[suitable_index].Release();
            }
        }
        finally
        {
            chunkReadersMutex[suitable_index].ReleaseMutex();
        }
        return s;
    }

    public void setCell(int row, int col, String str)
    {
        // set the string at [row,col]
        int suitable_index = get_Lock_index(row, col);


        chunkWritersMutex[suitable_index].Wait();
        matrix[row, col] = str;
        chunkWritersMutex[suitable_index].Release();
    }
    public Tuple<int, int> searchString(String str)
    {

        int row = -1, col = -1;
        // return first cell indexes that contains the string (search from first row to the last row)
        if (searchSemaphore != null)
        {
            searchSemaphore.WaitOne();
        }

        HashSet<int> locations = new HashSet<int>();
        bool found = false;

        for (int i = 0; i < rows; i++)
        {
            for (int j = 0; j < cols; j++)
            {
                int suitable_index = get_Lock_index(i, j);
                locations.Add(suitable_index);
            }
        }
        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();
        for (int j = 0; j < ordered_indexes.Count; j++)
        {
            chunkReadersMutex[ordered_indexes[j]].WaitOne();
            chunkReadersNum[ordered_indexes[j]]++;
            if (chunkReadersNum[ordered_indexes[j]] == 1)
            {
                chunkWritersMutex[ordered_indexes[j]].Wait();
            }
            chunkReadersMutex[ordered_indexes[j]].ReleaseMutex();
        }

        try
        {
            for (int i = 0; i < rows; i++)
            {
                for (int j = 0; j < cols; j++)
                {
                    if (this.matrix[i, j].Equals(str))
                    {
                        row = i;
                        col = j;
                        found = true;
                        break;
                    }
                }
                if (found)
                {
                    break;
                }
            }
        }
        finally
        {
            for (int j = 0; j < ordered_indexes.Count; j++)
            {
                chunkReadersMutex[ordered_indexes[j]].WaitOne();
                chunkReadersNum[ordered_indexes[j]]--;
                if (chunkReadersNum[ordered_indexes[j]] == 0)
                {
                    chunkWritersMutex[ordered_indexes[j]].Release();
                }
                chunkReadersMutex[ordered_indexes[j]].ReleaseMutex();
            }
            if (searchSemaphore != null)
            {
                searchSemaphore.Release();
            }
        }
        if (!found)
        {
            return null;
        }
        return Tuple.Create(row, col);
    }
    public void exchangeRows(int row1, int row2)
    {

        // exchange the content of row1 and row2
        if (row1 < 0 || row1 >= this.rows || row2 < 0 || row2 >= this.rows)
        {
            throw new ArgumentOutOfRangeException("wrong rows indexes");
        }
        if (row1 > row2)
        {
            int temp = row1;
            row1 = row2;
            row2 = temp;
        }
        HashSet<int> locations = new HashSet<int>();

        for (int j = 0; j < this.cols; j++)
        {
            int suitable_index1 = get_Lock_index(row1, j);
            int suitable_index2 = get_Lock_index(row2, j);
            locations.Add(suitable_index1);
            locations.Add(suitable_index2);
        }

        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();

        for (int i = 0; i < ordered_indexes.Count; i++)
        {
            chunkWritersMutex[ordered_indexes[i]].Wait();
        }

        try
        {
            for (int j = 0; j < this.cols; j++)
            {
                String temp = matrix[row1, j];
                matrix[row1, j] = matrix[row2, j];
                matrix[row2, j] = temp;
            }
        }
        finally
        {
            for (int i = 0; i < ordered_indexes.Count; i++)
            {
                chunkWritersMutex[ordered_indexes[i]].Release();
            }
        }
    }
    public void exchangeCols(int col1, int col2)
    {

        // exchange the content of col1 and col2
        // exchange the content of row1 and row2
        if (col1 < 0 || col1 >= this.cols || col2 < 0 || col2 >= this.cols)
        {
            throw new ArgumentOutOfRangeException("wrong indexes");
        }
        if (col1 > col2)
        {
            int temp = col1;
            col1 = col2;
            col2 = temp;
        }
        HashSet<int> locations = new HashSet<int>();

        for (int i = 0; i < this.rows; i++)
        {
            int suitable_index1 = get_Lock_index(i, col1);
            int suitable_index2 = get_Lock_index(i, col2);
            locations.Add(suitable_index1);
            locations.Add(suitable_index2);
        }

        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();

        for (int i = 0; i < ordered_indexes.Count; i++)
        {
            chunkWritersMutex[ordered_indexes[i]].Wait();
        }

        try
        {
            for (int i = 0; i < this.rows; i++)
            {
                String temp = matrix[i, col1];
                matrix[i, col1] = matrix[i, col2];
                matrix[i, col2] = temp;
            }
        }
        finally
        {
            for (int i = 0; i < ordered_indexes.Count; i++)
            {
                chunkWritersMutex[ordered_indexes[i]].Release();
            }
        }

    }
    public int searchInRow(int row, String str)
    {
        if (row < 0 || row >= this.rows)
        {
            throw new ArgumentOutOfRangeException("wrong index");
        }

        if (searchSemaphore != null)
        {
            searchSemaphore.WaitOne();
        }
        int col = -1;
        bool found = false;
        // perform search in specific row
        if (row < 0 || row >= this.rows)
        {
            throw new ArgumentOutOfRangeException("row out of bounds");
        }

        HashSet<int> locations = new HashSet<int>();

        for (int j = 0; j < this.cols; j++)
        {
            int suitable_index = get_Lock_index(row, j);
            locations.Add(suitable_index);
        }

        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();

        for (int j = 0; j < ordered_indexes.Count; j++)
        {
            chunkReadersMutex[ordered_indexes[j]].WaitOne();
            chunkReadersNum[ordered_indexes[j]]++;
            if (chunkReadersNum[ordered_indexes[j]] == 1)
            {
                chunkWritersMutex[ordered_indexes[j]].Wait();
            }
            chunkReadersMutex[ordered_indexes[j]].ReleaseMutex();
        }
        try
        {
            for (int j = 0; j < this.cols; j++)
            {
                if (matrix[row, j].Equals(str))
                {
                    col = j;
                    found = true;
                    break;
                }
            }
        }
        finally
        {
            for (int j = 0; j < ordered_indexes.Count; j++)
            {
                chunkReadersMutex[ordered_indexes[j]].WaitOne();
                chunkReadersNum[ordered_indexes[j]]--;
                if (chunkReadersNum[ordered_indexes[j]] == 0)
                {
                    chunkWritersMutex[ordered_indexes[j]].Release();
                }
                chunkReadersMutex[ordered_indexes[j]].ReleaseMutex();
            }
            if (searchSemaphore != null)
            {
                searchSemaphore.Release();
            }
        }
        if (found)
        {
            return col;
        }
        return -1;
    }
    public int searchInCol(int col, String str)
    {
        if (col < 0 || col >= this.cols)
        {
            throw new ArgumentOutOfRangeException("wrong index");
        }

        if (searchSemaphore != null)
        {
            searchSemaphore.WaitOne();
        }
        int row = -1;
        bool found = false;
        // perform search in specific col

        HashSet<int> locations = new HashSet<int>();

        for (int i = 0; i < this.rows; i++)
        {
            int suitable_index = get_Lock_index(i, col);
            locations.Add(suitable_index);
        }

        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();

        for (int i = 0; i < ordered_indexes.Count; i++)
        {
            chunkReadersMutex[ordered_indexes[i]].WaitOne();
            chunkReadersNum[ordered_indexes[i]]++;
            if (chunkReadersNum[ordered_indexes[i]] == 1)
            {
                chunkWritersMutex[ordered_indexes[i]].Wait();
            }
            chunkReadersMutex[ordered_indexes[i]].ReleaseMutex();
        }
        try
        {
            for (int i = 0; i < this.rows; i++)
            {
                if (matrix[i, col].Equals(str))
                {
                    row = i;
                    found = true;
                    break;
                }
            }
        }
        finally
        {
            for (int i = 0; i < ordered_indexes.Count; i++)
            {
                chunkReadersMutex[ordered_indexes[i]].WaitOne();
                chunkReadersNum[ordered_indexes[i]]--;
                if (chunkReadersNum[ordered_indexes[i]] == 0)
                {
                    chunkWritersMutex[ordered_indexes[i]].Release();
                }
                chunkReadersMutex[ordered_indexes[i]].ReleaseMutex();
            }
            if (searchSemaphore != null)
            {
                searchSemaphore.Release();
            }
        }
        if (found)
        {
            return row;
        }
        return -1;
    }
    public Tuple<int, int> searchInRange(int col1, int col2, int row1, int row2, String str)
    {
        if (col1 < 0 || col1 >= this.cols || col2 < 0 || col2 >= this.cols || row1 < 0 || row1 >= this.rows || row2 < 0 || row2 >= this.rows || row1 > row2 || col1 > col2)
        {
            throw new ArgumentOutOfRangeException("wrong indexes");
        }

        if (searchSemaphore != null)
        {
            searchSemaphore.WaitOne();
        }
        int row = -1, col = -1;
        bool found = false;
        // perform search within spesific range: [row1:row2,col1:col2] 
        //includes col1,col2,row1,row2

        HashSet<int> locations = new HashSet<int>();

        for (int i = row1; i <= row2; i++)
        {
            for (int j = col1; j <= col2; j++)
            {
                int suitable_index = get_Lock_index(i, j);
                locations.Add(suitable_index);
            }
        }
        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();
        for (int j = 0; j < ordered_indexes.Count; j++)
        {
            chunkReadersMutex[ordered_indexes[j]].WaitOne();
            chunkReadersNum[ordered_indexes[j]]++;
            if (chunkReadersNum[ordered_indexes[j]] == 1)
            {
                chunkWritersMutex[ordered_indexes[j]].Wait();
            }
            chunkReadersMutex[ordered_indexes[j]].ReleaseMutex();
        }

        try
        {
            for (int i = row1; i <= row2; i++)
            {
                for (int j = col1; j <= col2; j++)
                {
                    if (matrix[i, j].Equals(str))
                    {
                        row = i;
                        col = j;
                        found = true;
                        break;
                    }
                }
                if (found)
                {
                    break;
                }
            }
        }
        finally
        {
            for (int j = 0; j < ordered_indexes.Count; j++)
            {
                chunkReadersMutex[ordered_indexes[j]].WaitOne();
                chunkReadersNum[ordered_indexes[j]]--;
                if (chunkReadersNum[ordered_indexes[j]] == 0)
                {
                    chunkWritersMutex[ordered_indexes[j]].Release();
                }
                chunkReadersMutex[ordered_indexes[j]].ReleaseMutex();
            }
            if (searchSemaphore != null)
            {
                searchSemaphore.Release();
            }
        }
        if (!found)
        {
            return null;
        }
        return Tuple.Create(row, col);
    }


    public void addRow(int row1)
    {
        //add a row after row1

        // lock all as writers because has to copy the matrixes - including the ints matrix which readers change it. so no readers can ooperate while the add.

        if (row1 < 0 || row1 >= this.rows)
        {
            throw new ArgumentOutOfRangeException("wrong index");
        }

        HashSet<int> locations = new HashSet<int>();

        for (int i = 0; i < rows; i++)
        {
            for (int j = 0; j < cols; j++)
            {
                int suitable_index = get_Lock_index(i, j);
                locations.Add(suitable_index);
            }
        }
        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();

        for (int j = 0; j < ordered_indexes.Count; j++)
        {
            chunkWritersMutex[ordered_indexes[j]].Wait();
        }


        String[,] new_matrix;

        try
        {
            new_matrix = new string[rows + 1, cols];

            for (int i = 0; i < rows + 1; i++)
            {
                for (int j = 0; j < cols; j++)
                {
                    if (i <= row1)
                    {
                        new_matrix[i, j] = matrix[i, j];
                    }
                    else
                    {
                        if (i == row1 + 1)
                        {
                            new_matrix[i, j] = "";
                        }
                        else
                        {
                            new_matrix[i, j] = matrix[i - 1, j];
                        }

                    }
                }

            }
            this.matrix = new_matrix;
            this.rows += 1;
        }
        finally
        {
            for (int j = 0; j < ordered_indexes.Count; j++)
            {
                chunkWritersMutex[ordered_indexes[j]].Release();
            }
        }

    }
    public void addCol(int col1)
    {
        if (col1 < 0 || col1 >= this.cols)
        {
            throw new ArgumentOutOfRangeException("wrong index");
        }

        HashSet<int> locations = new HashSet<int>();
        //add a column after col1
        for (int i = 0; i < rows; i++)
        {
            for (int j = 0; j < cols; j++)
            {
                int suitable_index = get_Lock_index(i, j);
                locations.Add(suitable_index);
            }
        }
        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();

        for (int j = 0; j < ordered_indexes.Count; j++)
        {
            chunkWritersMutex[ordered_indexes[j]].Wait();
        }


        String[,] new_matrix;

        try
        {
            new_matrix = new string[rows, cols + 1];

            for (int i = 0; i < rows; i++)
            {
                for (int j = 0; j < cols + 1; j++)
                {
                    if (j <= col1)
                    {
                        new_matrix[i, j] = matrix[i, j];
                    }
                    else
                    {
                        if (j == col1 + 1)
                        {
                            new_matrix[i, j] = "";
                        }
                        else
                        {
                            new_matrix[i, j] = matrix[i, j - 1];
                        }
                    }
                }

            }
            this.matrix = new_matrix;
            this.cols++;
        }
        finally
        {
            for (int j = 0; j < ordered_indexes.Count; j++)
            {
                chunkWritersMutex[ordered_indexes[j]].Release();
            }
        }
    }
    public Tuple<int, int>[] findAll(String str, bool caseSensitive)
    {
        // perform search and return all relevant cells according to caseSensitive param
        if (searchSemaphore != null)
        {
            searchSemaphore.WaitOne();
        }
        List<Tuple<int, int>> res = new List<Tuple<int, int>>();

        HashSet<int> locations = new HashSet<int>();

        for (int i = 0; i < rows; i++)
        {
            for (int j = 0; j < cols; j++)
            {
                int suitable_index = get_Lock_index(i, j);
                locations.Add(suitable_index);
            }
        }
        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();
        for (int j = 0; j < ordered_indexes.Count; j++)
        {
            chunkReadersMutex[ordered_indexes[j]].WaitOne();
            chunkReadersNum[ordered_indexes[j]]++;
            if (chunkReadersNum[ordered_indexes[j]] == 1)
            {
                chunkWritersMutex[ordered_indexes[j]].Wait();
            }
            chunkReadersMutex[ordered_indexes[j]].ReleaseMutex();
        }


        try
        {
            String str_in_lower = str.ToLower();
            for (int i = 0; i < rows; i++)
            {
                for (int j = 0; j < cols; j++)
                {
                    String here = this.matrix[i, j];
                    if (!caseSensitive)
                    {
                        String here_to_check = here.ToLower();
                        if (here_to_check.Equals(str_in_lower))
                        {
                            res.Add(Tuple.Create(i, j));
                        }
                    }
                    else
                    {
                        if (here.Equals(str))
                        {
                            res.Add(Tuple.Create(i, j));
                        }
                    }
                }
            }
        }
        finally
        {
            for (int j = 0; j < ordered_indexes.Count; j++)
            {
                chunkReadersMutex[ordered_indexes[j]].WaitOne();
                chunkReadersNum[ordered_indexes[j]]--;
                if (chunkReadersNum[ordered_indexes[j]] == 0)
                {
                    chunkWritersMutex[ordered_indexes[j]].Release();
                }
                chunkReadersMutex[ordered_indexes[j]].ReleaseMutex();
            }
            if (searchSemaphore != null)
            {
                searchSemaphore.Release();
            }
        }
        return res.ToArray();
    }

    public void setAll(String oldStr, String newStr, bool caseSensitive)
    {
        // replace all oldStr cells with the newStr str according to caseSensitive param

        HashSet<int> locations = new HashSet<int>();

        for (int i = 0; i < rows; i++)
        {
            for (int j = 0; j < cols; j++)
            {
                int suitable_index = get_Lock_index(i, j);
                locations.Add(suitable_index);
            }
        }
        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();
        for (int j = 0; j < ordered_indexes.Count; j++)
        {
            chunkWritersMutex[ordered_indexes[j]].Wait();
        }
        try
        {

            String old_str_in_lower = oldStr.ToLower();
            for (int i = 0; i < rows; i++)
            {
                for (int j = 0; j < cols; j++)
                {
                    String here = this.matrix[i, j];
                    if (!caseSensitive)
                    {
                        String here_to_check = here.ToLower();
                        if (here_to_check.Equals(old_str_in_lower))
                        {
                            this.matrix[i, j] = newStr;
                        }
                    }
                    else
                    {
                        if (here.Equals(oldStr))
                        {
                            this.matrix[i, j] = newStr;
                        }
                    }
                }
            }
        }
        finally
        {
            for (int j = 0; j < ordered_indexes.Count; j++)
            {
                chunkWritersMutex[ordered_indexes[j]].Release();
            }
        }
    }


    public Tuple<int, int> getSize()
    {
        int nRows, nCols;
        // return the size of the spreadsheet in nRows, nCols
        return Tuple.Create(this.rows, this.cols); ;
    }

    public void save(String fileName)
    {
        // save the spreadsheet to a file fileName.
        // you can decide the format you save the data. There are several options.
        HashSet<int> locations = new HashSet<int>();

        for (int i = 0; i < rows; i++)
        {
            for (int j = 0; j < cols; j++)
            {
                int suitable_index = get_Lock_index(i, j);
                locations.Add(suitable_index);
            }
        }
        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();

        for (int j = 0; j < ordered_indexes.Count; j++)
        {
            chunkWritersMutex[ordered_indexes[j]].Wait();
        }

        StreamWriter writer = null;

        try
        {
            writer = new StreamWriter(fileName);
            writer.WriteLine(rows + "," + cols);
            for (int i = 0; i < rows; ++i)
            {
                String line = "";
                for (int j = 0; j < cols; ++j)
                {
                    line += this.matrix[i, j];
                    if (j != cols - 1)
                    {
                        line += " ";
                    }
                }
                writer.WriteLine(line);
            }
        }
        finally
        {
            if (writer != null)
            {
                writer.Close();
            }
            for (int j = 0; j < ordered_indexes.Count; j++)
            {
                chunkWritersMutex[ordered_indexes[j]].Release();
            }
        }
    }
    public void load(String fileName)
    {
        // load the spreadsheet from fileName
        // replace the data and size of the current spreadsheet with the loaded data
        HashSet<int> locations = new HashSet<int>();

        for (int i = 0; i < rows; i++)
        {
            for (int j = 0; j < cols; j++)
            {
                int suitable_index = get_Lock_index(i, j);
                locations.Add(suitable_index);
            }
        }
        List<int> ordered_indexes = new List<int>(locations);
        ordered_indexes.Sort();

        for (int j = 0; j < ordered_indexes.Count; j++)
        {
            chunkWritersMutex[ordered_indexes[j]].Wait();
        }

        StreamReader reader = null;

        try
        {
            reader = new StreamReader(fileName);
            String line = reader.ReadLine();
            int row_size = int.Parse(line.Split(",")[0]);
            int col_size = int.Parse(line.Split(",")[1]);
            String[,] new_matrix = new string[row_size, col_size];
            int row_index = 0;
            int col_index = 0;
            while ((line = reader.ReadLine()) != null)
            {
                String[] line_strings = line.Split(" ");
                foreach (String s in line_strings)
                {
                    new_matrix[row_index, col_index] = s;
                    col_index++;
                }
                col_index = 0;
                row_index++;
            }

            this.matrix = new_matrix;
            this.rows = row_size;
            this.cols = col_size;
        }

        finally
        {
            if (reader != null)
            {
                reader.Close();
            }
            for (int j = 0; j < ordered_indexes.Count; j++)
            {
                chunkWritersMutex[ordered_indexes[j]].Release();
            }
        }
    }
}



