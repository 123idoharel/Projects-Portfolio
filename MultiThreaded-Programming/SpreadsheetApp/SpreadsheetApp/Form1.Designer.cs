namespace SpreadsheetApp
{
    partial class Form1
    {
        /// <summary>
        ///  Required designer variable.
        /// </summary>
        private System.ComponentModel.IContainer components = null;

        /// <summary>
        ///  Clean up any resources being used.
        /// </summary>
        /// <param name="disposing">true if managed resources should be disposed; otherwise, false.</param>
        protected override void Dispose(bool disposing)
        {
            if (disposing && (components != null))
            {
                components.Dispose();
            }
            base.Dispose(disposing);
        }

        #region Windows Form Designer generated code

        /// <summary>
        ///  Required method for Designer support - do not modify
        ///  the contents of this method with the code editor.
        /// </summary>
        private void InitializeComponent()
        {
            dataGridView1 = new DataGridView();
            load_button = new Button();
            save_button = new Button();
            edit_button = new Button();
            row_text_box = new TextBox();
            col_text_box = new TextBox();
            value_text_box = new TextBox();
            label1 = new Label();
            label2 = new Label();
            label3 = new Label();
            ((System.ComponentModel.ISupportInitialize)dataGridView1).BeginInit();
            SuspendLayout();
            // 
            // dataGridView1
            // 
            dataGridView1.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.AutoSize;
            dataGridView1.Location = new Point(224, 36);
            dataGridView1.Name = "dataGridView1";
            dataGridView1.RowHeadersWidth = 51;
            dataGridView1.Size = new Size(318, 301);
            dataGridView1.TabIndex = 0;
            this.dataGridView1.CellValueChanged += new System.Windows.Forms.DataGridViewCellEventHandler(this.dataGridView1_CellValueChanged);
            // 
            // load_button
            // 
            load_button.Location = new Point(614, 154);
            load_button.Name = "load_button";
            load_button.Size = new Size(130, 64);
            load_button.TabIndex = 1;
            load_button.Text = "Load";
            load_button.UseVisualStyleBackColor = true;
            load_button.Click += button1_Click;
            // 
            // save_button
            // 
            save_button.Location = new Point(32, 154);
            save_button.Name = "save_button";
            save_button.Size = new Size(119, 63);
            save_button.TabIndex = 2;
            save_button.Text = "save";
            save_button.UseVisualStyleBackColor = true;
            save_button.Click += button2_Click;
            // 
            // edit_button
            // 
            edit_button.Location = new Point(126, 372);
            edit_button.Name = "edit_button";
            edit_button.Size = new Size(148, 45);
            edit_button.TabIndex = 3;
            edit_button.Text = "Edit";
            edit_button.UseVisualStyleBackColor = true;
            edit_button.Click += edit_button_Click;
            // 
            // row_text_box
            // 
            row_text_box.Location = new Point(318, 381);
            row_text_box.Name = "row_text_box";
            row_text_box.Size = new Size(89, 27);
            row_text_box.TabIndex = 4;
            // 
            // col_text_box
            // 
            col_text_box.Location = new Point(465, 381);
            col_text_box.Name = "col_text_box";
            col_text_box.Size = new Size(107, 27);
            col_text_box.TabIndex = 5;
            // 
            // value_text_box
            // 
            value_text_box.Location = new Point(631, 381);
            value_text_box.Name = "value_text_box";
            value_text_box.Size = new Size(113, 27);
            value_text_box.TabIndex = 6;
            // 
            // label1
            // 
            label1.AutoSize = true;
            label1.Location = new Point(660, 358);
            label1.Name = "label1";
            label1.Size = new Size(45, 20);
            label1.TabIndex = 7;
            label1.Text = "Value";
            // 
            // label2
            // 
            label2.AutoSize = true;
            label2.Location = new Point(492, 358);
            label2.Name = "label2";
            label2.Size = new Size(31, 20);
            label2.TabIndex = 8;
            label2.Text = "Col";
            // 
            // label3
            // 
            label3.AutoSize = true;
            label3.Location = new Point(338, 358);
            label3.Name = "label3";
            label3.Size = new Size(38, 20);
            label3.TabIndex = 9;
            label3.Text = "Row";
            // 
            // Form1
            // 
            AutoScaleDimensions = new SizeF(8F, 20F);
            AutoScaleMode = AutoScaleMode.Font;
            ClientSize = new Size(800, 450);
            Controls.Add(label3);
            Controls.Add(label2);
            Controls.Add(label1);
            Controls.Add(value_text_box);
            Controls.Add(col_text_box);
            Controls.Add(row_text_box);
            Controls.Add(edit_button);
            Controls.Add(save_button);
            Controls.Add(load_button);
            Controls.Add(dataGridView1);
            Name = "Form1";
            Text = "Form1";
            //this.Load += new System.EventHandler(this.Form1_Load);
            ((System.ComponentModel.ISupportInitialize)dataGridView1).EndInit();
            ResumeLayout(false);
            PerformLayout();
        }

        #endregion

        private DataGridView dataGridView1;
        private Button load_button;
        private Button save_button;
        private Button edit_button;
        private TextBox row_text_box;
        private TextBox col_text_box;
        private TextBox value_text_box;
        private Label label1;
        private Label label2;
        private Label label3;
    }
}
