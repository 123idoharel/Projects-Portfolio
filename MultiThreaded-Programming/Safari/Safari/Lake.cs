using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace Safari
{
    public class Lake
    {
        // holds the lake's attributes and panel representation. also maintains array of valid positions and an arrays represents if its filled, 
        // and by which animal. we locate animals by the available positions and the given rules and update the available positions.
        // we use a flag for the existance of hipo, so if an hipo waits - no one will enter the lake - to prevent starvation.
        // we use representation functions to reflect on the gui.
        // each locating action is locked with mutex.

        private int capacity;
        private String name;
        private Panel panel;

        private Point[] valid_positions;
        private Boolean[] filled;
        private String[] filled_with;
        private Form1 form;

        private bool is_hipo_wait = false;
        private Mutex is_hipo_wait_mutex = new Mutex();

        private Mutex locate_mutex = new Mutex();

        // constructor
        public Lake(int capacity, string name, Panel panel)
        {
            this.capacity = capacity;
            this.name = name;
            this.panel = panel;
            this.panel.BackgroundImage = Image.FromFile(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "images", "lake.jpg"));
            this.panel.BackgroundImageLayout = ImageLayout.Stretch;

            // create the possible positions array and mark all positions as not filled at start.

            this.valid_positions = this.create_positions_array();
            this.filled = new Boolean[valid_positions.Length];
            this.filled_with = new String[valid_positions.Length];
            for (int i = 0; i < filled.Length; i++) {
                filled[i] = false;
                filled_with[i] = "";
            }
        }

        // the function that's being sent to each thread. manages the drink. 
        // if hipo comes - we mark that hipo waits and wait until he can use the entire lake. 
        // the flag essures that no one will enter the lake while the hipo waits - so no starvation. 
        // if zebra or flamingo comes - if hipo waits they can't enter until the hipo finishes.
        // each animal locks the lake placement, checks if it has the place it needed, if not - releases, waits, and try again.
        // if can - takes the positions, drinks, and finishes. 
        public void letAnimalDrink(Animal animal, Form1 form)
        {
            this.form = form;
            Thread.Sleep((int)(animal.get_arrival_time() * 1000));
            if (animal is Hippopotamus)
            {
                // flag - protected by mutex
                is_hipo_wait_mutex.WaitOne();
                is_hipo_wait = true;
                is_hipo_wait_mutex.ReleaseMutex();

                // the check loop
                while (true)
                {
                    locate_mutex.WaitOne();
                    bool ok = true;
                    for (int i = 0; i < capacity; i++)
                    {
                        if (filled[i])
                        {
                            ok = false;
                            break;
                        }
                    }
                    if (ok)
                    {
                        break;
                    }
                    else
                    {
                        locate_mutex.ReleaseMutex();
                        Thread.Sleep(500);
                        continue;
                    }

                }
                // found places - fills
                for (int i = 0; i < capacity; i++)
                {
                    filled[i] = true;
                    filled_with[i] = "Hipo";
                }

                // updates the gui
                addAnimalToRepresentation(animal, 0);
                locate_mutex.ReleaseMutex();
                // the drink
                Thread.Sleep((int)animal.get_drinking_time() * 1000);

                //removes from lake
                locate_mutex.WaitOne();
                for (int i = 0; i < capacity; i++)
                {
                    filled[i] = false;
                    filled_with[i] = "";
                }

                // update flag
                is_hipo_wait_mutex.WaitOne();
                is_hipo_wait = false;
                is_hipo_wait_mutex.ReleaseMutex();

                removeAnimalFromRepresentation(animal.getID());
                locate_mutex.ReleaseMutex();


            }
            else // zebra or flamingo
            {
                while (true)
                {
                    // if hipo waits - cant enter
                    is_hipo_wait_mutex.WaitOne();
                    bool skip = is_hipo_wait;
                    is_hipo_wait_mutex.ReleaseMutex();
                    if (skip)
                    {
                        Thread.Sleep(500);
                        continue;
                    }

                    if (animal is Zebra)
                    {
                        int insertion_index = -99;

                        bool ok = false;

                        // looks for 2 positions in a row
                        while (true)
                        {
                            locate_mutex.WaitOne();
                            for (int i = 0; i < capacity - 1; i++)
                            {
                                if (filled[i] == false && filled[i + 1] == false)
                                {
                                    // found - fills the positions
                                    ok = true;
                                    insertion_index = i;
                                    filled[i] = true;
                                    filled[i + 1] = true;
                                    filled_with[i] = "Zebra";
                                    filled_with[i + 1] = "Zebra";
                                    break;
                                }
                            }
                            if (!ok) // not fount - retry
                            {
                                locate_mutex.ReleaseMutex();
                                Thread.Sleep(500);
                                continue;
                            }
                            else // found - continue to representation update
                            {
                                break;
                            }
                        }
                        addAnimalToRepresentation(animal, insertion_index);
                        locate_mutex.ReleaseMutex();

                        Thread.Sleep((int)animal.get_drinking_time() * 1000);

                        locate_mutex.WaitOne();
                        filled_with[insertion_index] = "";
                        filled_with[insertion_index + 1] = "";
                        filled[insertion_index] = false;
                        filled[insertion_index + 1] = false;

                        removeAnimalFromRepresentation(animal.getID());
                        locate_mutex.ReleaseMutex();

                    }

                    else // flamingo
                    {
                        bool ok = false;
                        int insertion_index = -99;
                        while (true)
                        {
                            locate_mutex.WaitOne();
                            bool there_is = false;
                            for (int i = 0; i < capacity; i++) {
                                if (filled_with[i] == "Flamingo")
                                {
                                    there_is = true;
                                }
                            }
                            for (int i = 0; i < capacity; i++)
                            {
                                // looks for flamingo in one side or that there is no flamingo in the lake
                                if ((filled[i] == false) && ((there_is == false) || (i ==0 && filled_with[i+1] == "Flamingo") || (i==capacity - 1 && filled_with[i-1] == "Flamingo") || (i>0 && i < capacity - 1 && (filled_with[i-1] == "Flamingo" || filled_with[i+1] == "Flamingo"))))
                                {
                                    ok = true;
                                    insertion_index = i;
                                    filled[i] = true;
                                    filled_with[i] = "Flamingo";
                                    break;
                                }

                            }
                            if (!ok)
                            {
                                locate_mutex.ReleaseMutex();
                                Thread.Sleep(500);
                                continue;
                            }
                            else
                            {
                                break;
                            }
                        }
                        addAnimalToRepresentation(animal, insertion_index);
                        locate_mutex.ReleaseMutex();

                        Thread.Sleep((int)animal.get_drinking_time() * 1000);

                        locate_mutex.WaitOne();
                        filled_with[insertion_index] = "";
                        filled[insertion_index] = false;
                        removeAnimalFromRepresentation(animal.getID());
                        locate_mutex.ReleaseMutex();


                    }


                }
            }
        }

        // create the positions array
        public Point[] create_positions_array() { 
            Point[] positions = new Point[capacity];
            int width_per_animal = panel.Width / capacity;
            int height_of_animals = panel.Height / 2;
            for (int i = 0; i < capacity; i++) {
                positions[i] = new Point(width_per_animal * i, height_of_animals);
            }
            return positions;
        }

        public void addAnimalToRepresentation(Animal animal, int position_index)
        {
            
            form.Invoke(() => // calls the GUI thread
            {
                // creates label with needed the data - using the tag

                Point insertion_place = valid_positions[position_index];
                Label representation = new Label();
                representation.BackgroundImage = get_image_path(animal);
                representation.BackgroundImageLayout = ImageLayout.Zoom;

                representation.Size = new Size((panel.Width - capacity + 4) / capacity, panel.Height * 3 / 4);
                if (animal is Hippopotamus)
                {
                    // needs to be seen as the whole lake
                    representation.Size = new Size(panel.Width, panel.Height * 3 / 4);
                }
                if (animal is Zebra)
                {
                    // needs to be seen as double position in the lake
                    representation.Size = new Size(2 * (panel.Width - capacity + 4) / capacity, panel.Height * 3 / 4);
                }
                representation.Tag = new int[2] { position_index, animal.getID() };
                if(animal is Zebra)
                {
                    representation.Tag = new int[3] { position_index, animal.getID(), -100 };
                }
                representation.Location = insertion_place;
                representation.BorderStyle = BorderStyle.FixedSingle;
                panel.Controls.Add(representation);
            });
        }

        public void removeAnimalFromRepresentation(int id)
        {
            try
            {

                // checks for each animal represented (control) if it's the correct one to remove by id
                foreach (Control appearance in panel.Controls)
                {
                    if (appearance is Label label && label.Tag is int[] tag && tag[1] == id)
                    {
                        form.Invoke(() =>
                        {
                            panel.Controls.Remove(appearance);
                           
                        });
                        
                        break;
                    }
                }
            }
            finally { ; }
        }

        public Image get_image_path(Animal animal)
        {
            // in order to always look at the correct path
            string basePath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "images");

            if (animal is Hippopotamus)
            {
                return Image.FromFile(Path.Combine(basePath, "hipo.jpg"));
            }
            if (animal is Zebra)
            {
                return Image.FromFile(Path.Combine(basePath, "zebra.png"));
            }
            else
            {
                return Image.FromFile(Path.Combine(basePath, "flamingo.jpg"));
            }
        }
    }
}
