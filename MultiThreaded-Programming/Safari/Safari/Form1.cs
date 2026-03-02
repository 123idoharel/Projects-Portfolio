namespace Safari
{
    public partial class Form1 : Form
    {
        private ManageLogic manageLogic;
        public Form1()
        {
            InitializeComponent();
        }

        // the user presses start - call the manage logic start. 
        private void button1_Click(object sender, EventArgs e)
        {
            this.manageLogic = new ManageLogic(this);
            this.manageLogic.start();
        }

    }
}