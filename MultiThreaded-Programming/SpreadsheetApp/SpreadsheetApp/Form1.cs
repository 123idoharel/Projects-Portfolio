using System.Net;
//using System;
//using System.Windows.Forms;


namespace SpreadsheetApp
{
    public partial class Form1 : Form
    {
        // the class holds a spreadsheet and a boolean variable marks if there is an update in the grid representaion
        // (in order to not change things when the represetnation is updating). 
        private SharableSpreadSheet SharableSpreadSheet;
        private bool is_updating = false;

        // constructor initializes the components, enables to edit the cuurent spreadsheet, and creates a default spreadsheet for start.
        public Form1()
        {
            InitializeComponent();

            dataGridView1.ReadOnly = false;
            this.SharableSpreadSheet = new SharableSpreadSheet(10, 10, 2);
            UpdateGrid();
        }

        // the load function - loads spreadsheet from file. 
        // gives an option to choose from all existing files checks if typed name is valid and updates the spreadsheet and grid if so.
        private void Load()
        {
            OpenFileDialog ofd = new OpenFileDialog();
            ofd.Filter = "Text Files (*.txt)|*.txt|All Files (*.*)|*.*";
            ofd.ShowDialog();
            string file = ofd.FileName;
            if (!string.IsNullOrWhiteSpace(file))
            {
                this.SharableSpreadSheet.load(file);
                UpdateGrid();
            }
        }

        // the grid update - after change in the spreadsheet updates the representaion. 
        // removes the existing representation and builds new one according to the current spreadsheet (which is already updated).
        private void UpdateGrid()
        {
            is_updating = true;
            dataGridView1.Rows.Clear();
            dataGridView1.Columns.Clear();
            for (int j = 0; j < this.SharableSpreadSheet.getSize().Item2; j++)
            {
                DataGridViewTextBoxColumn col = new DataGridViewTextBoxColumn();
                col.Name = $"col{j}";
                col.HeaderText = $"Column {j}";
                dataGridView1.Columns.Add(col);
            }
            for (int i = 0; i < this.SharableSpreadSheet.getSize().Item1; i++)
            {
                string[] row = new string[this.SharableSpreadSheet.getSize().Item2];

                for (int j = 0; j < this.SharableSpreadSheet.getSize().Item2; j++)
                {
                    row[j] = this.SharableSpreadSheet.getCell(i, j);
                }
                dataGridView1.Rows.Add(row);
            }
            is_updating = false;
        }

        // when user pressses load button - uses load function. 
        private void button1_Click(object sender, EventArgs e) // load button
        {
            Load();
        }

        // when user changes in the grid representation itself - update the spreadsheet. 
        private void dataGridView1_CellValueChanged(object sender, DataGridViewCellEventArgs e)
        {
            if (!is_updating)
            {
                object val_to_update = dataGridView1.Rows[e.RowIndex].Cells[e.ColumnIndex].Value;
                if (val_to_update != null)
                {
                    this.SharableSpreadSheet.setCell(e.RowIndex, e.ColumnIndex, val_to_update.ToString());
                }
            }
        }

        // when user presses Save button - loads exsiting files and user chooses an existing file or to save in new one,
        // check type validation and saves.
        private void button2_Click(object sender, EventArgs e) // save button
        {
            SaveFileDialog sfd = new SaveFileDialog();
            sfd.Filter = "Text Files (*.txt)|*.txt|All Files (*.*)|*.*";
            sfd.ShowDialog();
            string file = sfd.FileName;
            if (!string.IsNullOrWhiteSpace(file)){
                this.SharableSpreadSheet.save(file);
            }

        }

        // when user presses edit button - takes the values inserted to textboxes and updates spreadsheet and grid.
        private void edit_button_Click(object sender, EventArgs e)
        {
            int row = int.Parse(row_text_box.Text);
            int col = int.Parse(col_text_box.Text);
            String val = value_text_box.Text;
            this.SharableSpreadSheet.setCell(row, col, val);
            dataGridView1.Rows[row].Cells[col].Value = val;

        }
    }
}
