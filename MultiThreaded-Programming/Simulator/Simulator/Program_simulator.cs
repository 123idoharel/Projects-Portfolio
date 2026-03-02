
using System.Runtime.CompilerServices;

class Simulator
{
    // the Simulator class holds the needed arguments to operate.
    public SharableSpreadSheet SharableSpreadSheet;
    private int rows;
    private int cols;
    private int nThreads;
    private int nOperations;
    private int ms;

    // constructor sets the fields by arguments and fills the spreadsheet with "testcell{i}{j}";
    public Simulator( int rows, int cols, int nThreads, int nOperations, int ms)
    {
        this.rows = rows;
        this.cols = cols;
        this.nThreads = nThreads;
        this.nOperations = nOperations;
        this.ms = ms;
        this.SharableSpreadSheet= new SharableSpreadSheet(rows, cols);

        for (int i = 0; i < rows; i++) {
            for (int j = 0; j < cols; j++) {
                SharableSpreadSheet.setCell(i, j, $"testcell{i}{j}");
            }
        
        }
    }

    public static void Main(string[] args)
    {
        // receiving arguments
        int rows = int.Parse(args[0]);
        int cols = int.Parse(args[1]);
        int nThreads = int.Parse(args[2]);
        int nOperations = int.Parse(args[3]);
        int ms = int.Parse(args[4]);

        // creates Simulator object
        Simulator simulator = new Simulator(rows, cols, nThreads, nOperations, ms);

        // creates nThreads threads - each thread function is doWork - makes nOperations randomally.
        Thread[] threads = new Thread[nThreads];
        for (int i = 0; i < threads.Length; i++) {
            threads[i] = new Thread(() => doWork(nOperations, simulator.SharableSpreadSheet, ms, i));
            threads[i].Start();
        }
        // wait
        foreach (Thread thread in threads) {
            thread.Join();
        }

       
    }

    static void doWork(int nOperations, SharableSpreadSheet sharableSpreadSheet1, int ms, int id)
    {
       // the function that is inserted to each thread as it's function. manages the nOperations randomally for each thread.

        Random rand = new Random();
        for(int i=0; i < nOperations; i++)
        {
            int choice = rand.Next(0,13);
            // there are 13 possible functions- each int represents other.
            // searches - create and searches a possible String by format "testcell{i}{j}" with random i,j or just i or just j (if the row or column given)

            switch (choice){
                    case 0: // getCell
                    {
                        int row_index = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        int col_index = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        String res = sharableSpreadSheet1.getCell(row_index, col_index);
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{res}\" read cell [{row_index},{col_index}].");
                        break;
                    }
                    case 1: // setCell
                    {
                        int row_index = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        int col_index = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        String to_set = $"changed by {id} round {i}";
                        sharableSpreadSheet1.setCell(row_index , col_index , to_set);
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{to_set}\" inserted to cell [{row_index},{col_index}].");
                        break;
                    }
                case 2:// search string
                    {
                        int i1 = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        int j = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        String to_search = $"testcell{i1}{j}";
                        Tuple<int,int> res = sharableSpreadSheet1.searchString(to_search);
                        if(res == null)
                        {
                            Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{to_search}\" NOT found");
                            break;
                        }
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{to_search}\" found in [{res.Item1},{res.Item2}].");
                        break;
                    }
                case 3:// exchange rows
                    {
                        int row_index1 = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        int row_index2 = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        sharableSpreadSheet1.exchangeRows(row_index1, row_index2);
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] switched rows {row_index1} and {row_index2}.");
                        break;
                    }
                case 4: // exchange cols
                    {
                        int col_index1 = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        int col_index2 = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        sharableSpreadSheet1.exchangeCols(col_index1, col_index2);
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] switched cols {col_index1} and {col_index2}.");
                        break;
                    }
                    case 5: // search in row
                    {
                        int row_index = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        int j = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        String to_search = $"testcell{row_index}{j}";
                        int res = sharableSpreadSheet1.searchInRow(row_index, to_search);
                        if(res == -1)
                        {
                            Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{to_search}\" NOT found in row {row_index}");
                            break ;
                        }
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{to_search}\" found in row {row_index} in col {res}");
                        break;
                    }
                    case 6: // search in col
                    {
                        int col_index = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        int j = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        String to_search = $"testcell{j}{col_index}";
                        int res = sharableSpreadSheet1.searchInCol(col_index, to_search);
                        if (res == -1)
                        {
                            Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{to_search}\" NOT found in col {col_index}");
                            break;
                        }
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{to_search}\" found in col {col_index} in row {res}");
                        break;
                    }
                    case 7: // search in range
                    {
                        Tuple<int, int> size = sharableSpreadSheet1.getSize();
                        int row_index1 = rand.Next(0, size.Item1);
                        int row_index2 = rand.Next(0, size.Item1);
                        int col_index1 = rand.Next(0, size.Item2);
                        int col_index2 = rand.Next(0, size.Item2);
                        if (row_index1 > row_index2)
                        {
                            int temp = row_index1;
                            row_index1 = row_index2;
                            row_index2 = temp;
                        }
                        if (col_index1 > col_index2)
                        {
                            int temp = col_index1;
                            col_index1 = col_index2;
                            col_index2 = temp;
                        }
                        String to_search = $"testcell{row_index1 + 1}{col_index1 + 1}";
                        Tuple<int, int> res = null;
                        try
                        {
                            res = sharableSpreadSheet1.searchInRange(row_index1, row_index2, col_index1, col_index2, to_search);

                        }
                        catch(Exception e)
                        {
                            break;
                        }

                        if (res == null)
                        {
                            Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{to_search}\" NOT found in range: rows [{row_index1}: {row_index2}] cols: [{col_index1}: {col_index2}]");
                            break;
                        }
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string \"{to_search}\" found in range: rows [{row_index1}: {row_index2}] cols: [{col_index1}: {col_index2}] in [{res.Item1}, {res.Item2}]");
                        break;
                    }
                    case 8: // add row
                    {
                        int row_index = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        sharableSpreadSheet1.addRow(row_index);
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] added row after row {row_index}");
                        break;
                    }
                    case 9: // add col
                    {
                        int col_index = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        sharableSpreadSheet1.addCol(col_index);
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] added col after col {col_index}");
                        break;
                    }
                    case 10: // find all
                    {
                        Tuple<int, int>[] res = null;
                        int i1 = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        int j = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        String to_search = $"testcell{i1}{j}";
                        int sensitive = rand.Next(0,2);
                        if (sensitive == 0) {
                            res = sharableSpreadSheet1.findAll(to_search, false);
                        }
                        else
                        {
                            res = sharableSpreadSheet1.findAll(to_search, true);
                        }
                        if(res == null)
                        {
                            Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string {to_search} not found");
                            break;
                        }
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] string {to_search} found in: ");
                        for (int q = 0; q < res.Length; q++) { 
                            Console.WriteLine($" location: [{ res[q].Item1}, { res[q].Item2}]");
                        }
                        break;
                    }
                case 11: // set all
                    {
                        int i1 = rand.Next(0, sharableSpreadSheet1.getSize().Item1);
                        int j = rand.Next(0, sharableSpreadSheet1.getSize().Item2);
                        String to_search = $"testcell{i1}{j}";
                        String new_string = "replaced";
                        bool sensitive;
                        if (rand.Next(0, 2) == 0)
                        {
                            sensitive = false;
                        }
                        else
                        {
                            sensitive = true;
                        }
                        sharableSpreadSheet1.setAll(to_search, new_string, sensitive);
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] sel all {to_search} to : {new_string} ");

                        break;
                    }
                case 12: // get size
                    {
                        Tuple<int,int> res = sharableSpreadSheet1.getSize();
                        Console.WriteLine($"User [{id}]: [{DateTime.Now:HH:mm:ss}] got size: [{res.Item1}, {res.Item2}] ");
                        break;
                    }
            }
            Thread.Sleep(ms);
        }
    }
}